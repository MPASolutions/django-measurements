import logging

import pandas as pd

from measurements.models import Serie
from measurements.settings import QUALITY_CHECKS

logger = logging.getLogger(__name__)


class SerieQualityControl:
    """
    Quality control of the samples of a serie before they are written.

    The checks follow the cascade of WMO-No. 955 (Zahumensky 2004) and the marks follow the
    QARTOD convention. A FAIL is a value no sensor in air can report (outside the physical range,
    above the world record envelope of rainfall, an isolated spike no air temperature can do): it is
    never written. A SUSPECT is a value that can be real (a stuck sensor looks like a quiet night):
    it is written unchanged and reported, the decision is left to whoever consumes it.

    The limits are declared in MEASUREMENTS_QUALITY_CHECKS, keyed by the code of the parameter or
    by the code of its physical parameter: the first wins, so one provider can have its own limits
    while every parameter linked to a physical parameter gets the common ones. A parameter found
    under neither code is written unchecked.
    """

    PASS = 1
    SUSPECT = 3
    FAIL = 4

    def __init__(self, limits: dict[str, float | tuple[float, float]]) -> None:
        """Keep the limits declared for the parameter, as read from MEASUREMENTS_QUALITY_CHECKS."""
        self.limits = limits

    @classmethod
    def get_for_serie(cls, serie_id: int) -> "SerieQualityControl | None":
        """Return the control declared for the parameter of the serie, None when there is none."""
        codes = (
            Serie.objects.filter(pk=serie_id)
            .values_list("parameter__code", "parameter__physical_parameter__code")
            .first()
        )
        for code in codes or ():
            if code in QUALITY_CHECKS:
                return cls(QUALITY_CHECKS[code])
        return None

    def get_flags(self, timestamps: pd.Series, values: pd.Series) -> pd.Series:
        """
        Return a mark for every sample, aligned on the index of values.

        The checks run in cascade: the ones that look at the neighbours read the series without
        the samples already failed, so a single wrong value cannot hide or create another fault.
        Without a temporal index only the range check can run.
        """
        flags = pd.Series(self.PASS, index=values.index)
        flags[self.get_out_of_range(values)] = self.FAIL

        if not pd.api.types.is_datetime64_any_dtype(timestamps) or len(values) < 2:
            return flags

        order = timestamps.sort_values().index
        over_envelope = self.get_over_envelope(timestamps[order], values[order])
        flags[over_envelope[over_envelope].index] = self.FAIL
        good = order[flags[order] != self.FAIL]
        spikes = self.get_spikes(timestamps[good], values[good])
        flags[spikes[spikes].index] = self.FAIL

        good = order[flags[order] != self.FAIL]
        suspect = self.get_below_suspect_min(values[good]) | self.get_persistent(timestamps[good], values[good])
        flags[suspect[suspect].index] = self.SUSPECT
        return flags

    def get_out_of_range(self, values: pd.Series) -> pd.Series:
        """Values outside the physical range of the parameter."""
        out = pd.Series(False, index=values.index)
        if "min" in self.limits:
            out |= values < self.limits["min"]
        if "max" in self.limits:
            out |= values > self.limits["max"]
        return out

    def get_over_envelope(self, timestamps: pd.Series, values: pd.Series) -> pd.Series:
        """
        Accumulations above the envelope of the world rainfall records, P = a * D ** b mm for D hours.

        The accumulation period of a sample is not stored anywhere: the median step of the series is
        used instead, which on a regular series is exactly the period of the provider and stays
        unaffected by the holes of a transmission.
        """
        if "envelope" not in self.limits:
            return pd.Series(False, index=values.index)
        step_hours = timestamps.diff().median().total_seconds() / 3600
        if not step_hours:
            return pd.Series(False, index=values.index)
        coefficient, exponent = self.limits["envelope"]
        return values > coefficient * step_hours**exponent

    def get_spikes(self, timestamps: pd.Series, values: pd.Series) -> pd.Series:
        """
        Isolated spikes: a sample that departs from both neighbours in the same direction by more
        than the threshold, with both neighbours close in time.

        It is the neighbour form of the Hampel filter. The threshold is in the units of the parameter
        and only neighbours within spike_max_gap seconds are compared, so a gap in the series or a
        coarse step (forecasts every six hours) never turns a normal daily swing into a spike.
        """
        if "spike" not in self.limits:
            return pd.Series(False, index=values.index)
        max_gap = pd.Timedelta(seconds=self.limits["spike_max_gap"])
        rise = values - values.shift(1)
        fall = values - values.shift(-1)
        close = (timestamps - timestamps.shift(1) <= max_gap) & (timestamps.shift(-1) - timestamps <= max_gap)
        return close & (rise * fall > 0) & (rise.abs() > self.limits["spike"]) & (fall.abs() > self.limits["spike"])

    def get_below_suspect_min(self, values: pd.Series) -> pd.Series:
        """Values inside the physical range but below the lowest one a working sensor reports."""
        if "suspect_min" not in self.limits:
            return pd.Series(False, index=values.index)
        return values < self.limits["suspect_min"]

    def get_persistent(self, timestamps: pd.Series, values: pd.Series) -> pd.Series:
        """Runs of the very same value lasting at least persistence seconds: the sensor stopped moving."""
        if "persistence" not in self.limits:
            return pd.Series(False, index=values.index)
        run = (values != values.shift(1)).cumsum()
        start = timestamps.groupby(run).transform("min")
        end = timestamps.groupby(run).transform("max")
        return end - start >= pd.Timedelta(seconds=self.limits["persistence"])

    def log_flags(self, serie_id: int, timestamps: pd.Series, flags: pd.Series) -> None:
        """Report failed and suspect samples, with the first timestamp of each to find them."""
        for flag, label in ((self.FAIL, "failed and not written"), (self.SUSPECT, "suspect")):
            marked = timestamps[flags == flag]
            if marked.empty:
                continue
            logger.warning(f"Serie {serie_id}: {len(marked)} samples {label}, first at {marked.min()}")
