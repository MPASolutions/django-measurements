from datetime import datetime
import urllib3
urllib3.disable_warnings()
import pandas as pd
from bs4 import BeautifulSoup

from measurements.sources.base import BaseSource


class IocAPI(BaseSource):
    name = "ioc"

    def __init__(self, tz='UTC'):
        self.baseurl = "http://www.ioc-sealevelmonitoring.org/bgraph.php?code={}&output=tab&period=7"
        self.tz = tz

    def get_df(self, code, last=1):
        parameter = 'SLEV'

        r = self.download(self.baseurl.format(code), code)
        if r is None:
            self.df = None
            return None
        soup = BeautifulSoup(r.text, "html.parser")
        table = soup.find("table")
        if table is None:
            self.report_invalid_body(code, r, "a page with the data table")
            self.df = None
            return None
        rows = table.find_all('tr')
        data = []
        for row in rows[1:]:  # skip first row
            td = row.find_all('td')
            _time = datetime.strptime(td[0].text, "%Y-%m-%d %H:%M:%S")
            value = float(td[1].text)
            data.append([_time, value])
        df = pd.DataFrame(data, columns=['datetime', parameter])
        df.set_index('datetime', inplace=True)
        df = df.resample('30Min').nearest()
        self.df = df
        self.df.index = self.df.index.tz_localize(self.tz)

        return self.df

