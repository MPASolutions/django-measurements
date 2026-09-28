import os
import io
import datetime
import hmac
import hashlib
import urllib3
urllib3.disable_warnings()
import requests
import pandas as pd
from Crypto.Hash import HMAC
from Crypto.Hash import SHA256
import pytz

from measurements.sources.base import BaseSource

class ElmedAPI(BaseSource):
    def __init__(self, public_key, private_key, tz='Europe/Rome'):
        self.baseurl = "http://www.elmedweb.com/MeteoWeb/download/download.php?"
        self.public_key = public_key
        self.private_key = private_key
        self.tz = tz


    def get_df(self, code, last=24):
        end_date = datetime.datetime.today()
        start_date = end_date - datetime.timedelta(hours=last)
        payload = {"stationnr[]": code,
                   "auth": self.private_key,
                   "format": "csv_large",
                   "start_date": start_date.strftime('%d-%m-%Y'),
                   "end_date": end_date.strftime('%d-%m-%Y')
                   }
        try:
            r = requests.get(self.baseurl, params=payload, timeout=60)
        except requests.RequestException as e:
            print("ELMED: connection error for station {}: {}".format(code, e))
            self.df = None
            return None

        # the endpoint answers 200 even on its own internal failures, returning a
        # plain text message (e.g. "Error Database constructor") instead of a CSV
        if r.status_code != 200 or "Datum" not in r.text.split("\n", 1)[0]:
            print("ELMED: unexpected response for station {}: {}".format(code, r.text[:200]))
            self.df = None
            return None

        df = pd.read_csv(io.StringIO(r.text))

        # set datetime index
        df["Datum"] = pd.to_datetime(df["Datum"], format="%Y%m%d %H:%M:%S")
        df.set_index('Datum', inplace=True)
        self.df = df

        try:
            # try to localize the index. The datetime info is returned localized in
            # Europe/Rome already, but without the TZ info, and returns a single record
            # for ambiguous times.
            self.df.index = self.df.index.tz_localize(self.tz)
        except pytz.exceptions.AmbiguousTimeError:
            # when there is ambiguity because of DST, create a boolean array to specify
            # whether it's a DST time or not.
            # To do that, localize the records that work, drop those that do not work,
            # and select the latest DST info. This heuristic should allow to parse the
            # single returned ambiguous time with the "old" DST the first time it is
            # encountered, and with the "new" DST the second time.
            localized_index = self.df.index.tz_localize(self.tz, ambiguous="NaT")
            latest_ts_is_dst = localized_index.dropna()[-1].dst().seconds > 0

            ambiguous = localized_index.map(
                lambda d: d.dst().seconds > 0 if d is not pd.NaT else latest_ts_is_dst
            )
            self.df.index = self.df.index.tz_localize(self.tz, ambiguous=ambiguous)

        # the endpoint takes whole days and answers from midnight of start_date, so a
        # request for the last 24 hours returns up to 48: keep only the hours asked for
        since = pd.Timestamp.now(tz=self.tz) - pd.Timedelta(hours=last)
        self.df = self.df[self.df.index >= since]

        return self.df
