import os
import datetime
import hmac
import hashlib
import urllib3
urllib3.disable_warnings()
import pandas as pd
from Crypto.Hash import HMAC
from Crypto.Hash import SHA256


from measurements.sources.base import BaseSource

# v0 answers on the unversioned routes (/pretty/...), v2 needs an API subscription on the FieldClimate account
API_V0 = "v0"
API_V2 = "v2"


class PesslAPI(BaseSource):
    name = "pessl"

    def __init__(self, public_key, private_key, tz='Etc/GMT-1', api_version=API_V0):
        self.baseurl = "https://api.fieldclimate.com"
        self.public_key = public_key
        self.private_key = private_key
        self.tz = tz
        self.api_version = api_version

    def get_auth_headers(self, request, method="GET"):
        d = datetime.datetime.utcnow()
        timestamp = d.strftime('%a, %d %b %Y %H:%M:%S GMT')

        # Creating content to sign with private key
        msg = "{}{}{}{}".format(method, request,
                                        timestamp, self.public_key).encode(encoding='utf-8')

        # msg = (self._method + self._apiRoute + dateStamp + self._publicKey).encode(encoding='utf-8')
        h = HMAC.new(self.private_key.encode(encoding='utf-8'), msg, SHA256)
        signature = h.hexdigest()

        # Hash content to sign into HMAC signature
        # signing = hmac.new(self.private_key,
        #                   content_to_sign,
        #                   hashlib.sha256)

        headers = {
            "Accept": "application/json",
            "Authorization": "hmac {}:{}".format(self.public_key,
                                                 signature),
            "Request-Date" if self.api_version == API_V2 else "Date": "{}".format(timestamp)
        }
        return headers

    def _todf(self, data):
        _colindex = []
        columns = []
        _data = {}
        for sk, s in data['data'].items():
            for aggk, agg in s['aggr'].items():
                _key = "{}_{}".format(sk, aggk)
                columns.append(_key)
                _data[_key] = agg
                _colindex.append((s['name'], aggk))
        colindex = pd.MultiIndex.from_tuples(_colindex, names=['datetime', 'agg'])
        # gmt1 to utc
        # print data['dates']
        # ATTENZIONE: provvisoriamente bisogna forzare un shift di 1 ora per un problema alle API di pessl
        # index = pd.to_datetime(data['dates'])
        # Ora il bug e' stato sistemato lato Pessl
        index = pd.to_datetime(data['dates']) # + pd.to_timedelta(1, 'h')
        # print index
        # index = pd.to_datetime(index, unit='ms')
        df = pd.DataFrame(_data, columns=columns, index=index, dtype='float')
        df.columns = colindex

        vc = df.columns.value_counts()
        repeated_columns = vc[vc > 1].index
        if len(repeated_columns) > 0:
            # multiple columns with the same name, wtf ??
            # check if they are the same, if not, log an error also with the pyhton logger

            for rp in repeated_columns:
                df_0 = df[rp].iloc[:, 0].copy()
                for colidx in range(1, len(df[rp].columns)):
                    if not df_0.equals(df[rp].iloc[:, colidx]):
                        print(
                            f"Multiple columns with the same name found in Pessl data for {rp} selected the first one, but please check."  # noqa: E501
                        )

            df = df.loc[:, ~df.columns.duplicated()]

        return df


    def _get_data(self, code, route='pretty', last=1):
        """
        route: pretty, data, ...
        """
        if self.api_version == API_V2:
            return self._get_data_v2(code, last)

        request = "/{}/{}/raw/last/{}".format(route, code, last)
        headers = self.get_auth_headers(request)
        url = "{}{}".format(self.baseurl, request)
        r = self.download(url, code, headers=headers, verify=False)
        if r is None:
            return False
        try:
            data = r.json()
        except ValueError:
            self.report_invalid_body(code, r, "JSON")
            return False
        # _todf reads both keys: any other answer (e.g. an error object) would end in a KeyError
        if not isinstance(data, dict) or "data" not in data or "dates" not in data:
            self.report_invalid_body(code, r, "the JSON with the data and dates keys")
            return False
        return data

    def _get_data_v2(self, code, last):
        """Download from API v2 and return the data in the shape of the v0 pretty route read by _todf."""
        # the route is signed without the version prefix
        request = "/data/{}/raw/last/{}".format(code, last)
        headers = self.get_auth_headers(request)
        url = "{}/{}{}".format(self.baseurl, API_V2, request)
        r = self.download(url, code, headers=headers)
        if r is None:
            return False
        try:
            data = r.json()
        except ValueError:
            self.report_invalid_body(code, r, "JSON")
            return False
        if not isinstance(data, dict) or not isinstance(data.get("data"), list) or "dates" not in data:
            self.report_invalid_body(code, r, "the JSON with the data list and the dates key")
            return False
        # name is translated in the language of the account, name_original is the English one of PARAMETER_MAP;
        # calculated sensors have no name_original and no aggr, their aggregates are the keys of values
        sensors = {
            str(i): {"name": s.get("name_original", s["name"]), "aggr": s["values"]}
            for i, s in enumerate(data["data"])
        }
        return {"dates": data["dates"], "data": sensors}

    def get_df(self, code, last=24):
        d = self._get_data(code, route='pretty', last=last)
        if d is False:
            return None # get_df should return None when it fails
        self.df = self._todf(d)

        # merge level names: e.g. variable|aggregate
        self.df.columns = self.df.columns.map('|'.join).str.strip('|')

        # localize datetime index
        self.df.index = self.df.index.tz_localize(self.tz)
        return self.df

