"""O3: generate the synthetic portfolio with a fixed seed.

Counts are set exactly (section 5.2). Every GCA margin is hit by raking the facility sizes
(iterative proportional fitting) over all margins at once: stage and calibration grade
(SYN-PAR-05), country (5.3), regulatory approach (5.3), NACE section (5.5), the P06
government/bank split (5.3) and the ten largest connected groups (SYN-04). Grades are chosen so
the MIG-07 rule returns each facility's opening stage (SYN-PAR-08); since the owner decision of
18 October 2026 a share of S2 is S2 by a qualitative trigger alone (MIG-05, A30), so the reported
stage is "PD test or any trigger".
"""

from datetime import date, timedelta

import numpy as np
import pandas as pd

from foundation.matrices import lifetime_pd
from foundation.synth import config as cfg

MILLION = 1_000_000.0
STAGES = (1, 2, 3)


def largest_remainder(n: int, weights: dict) -> dict:
    """Integer counts summing to n, proportional to weights, at least one per key if n allows."""
    keys = list(weights)
    w = np.array([weights[k] for k in keys], dtype=float)
    w = w / w.sum()
    if n >= len(keys):
        counts = np.ones(len(keys), dtype=int)
        rest = n - len(keys)
    else:
        counts = np.zeros(len(keys), dtype=int)
        rest = n
    share = w * rest
    counts += np.floor(share).astype(int)
    left = n - counts.sum()
    order = np.argsort(-(share - np.floor(share)), kind="stable")
    counts[order[:left]] += 1
    return dict(zip(keys, counts.tolist()))


def ipf_table(seed: np.ndarray, row_targets: np.ndarray, col_targets: np.ndarray) -> np.ndarray:
    table = seed.astype(float).copy()
    for _ in range(10_000):
        table *= (row_targets / table.sum(axis=1))[:, None]
        table *= col_targets / table.sum(axis=0)
        if np.allclose(table.sum(axis=1), row_targets, rtol=1e-15, atol=0):
            break
    return table


def partition(n: int, sizes: list[tuple[int, float]], rng: np.random.Generator) -> list[int]:
    values = [s for s, _ in sizes]
    probs = np.array([p for _, p in sizes])
    out = []
    while n > 0:
        size = min(int(rng.choice(values, p=probs / probs.sum())), n)
        out.append(size)
        n -= size
    return out


def rake(x: np.ndarray, margins: list[tuple[np.ndarray, np.ndarray]], tol: float = 1e-14,
         max_iter: int = 20_000) -> np.ndarray:
    """Scale sizes so that every margin's category sums equal its targets."""
    x = x.astype(float).copy()
    for cats, targets in margins:
        sums = np.bincount(cats, minlength=len(targets))
        if ((targets > 0) & (sums == 0)).any():
            raise ValueError("a margin category with a positive target has no facility")
        if ((targets == 0) & (sums > 0)).any():
            raise ValueError("a margin category with a zero target has facilities")
    for _ in range(max_iter):
        for cats, targets in margins:
            sums = np.bincount(cats, weights=x, minlength=len(targets))
            factor = np.divide(targets, sums, out=np.ones_like(targets), where=sums > 0)
            x *= factor[cats]
        worst = 0.0
        for cats, targets in margins:
            sums = np.bincount(cats, weights=x, minlength=len(targets))
            mask = targets > 0
            worst = max(worst, float(np.max(np.abs(sums[mask] / targets[mask] - 1.0))))
        if worst < tol:
            return x
    raise ValueError(f"raking did not converge (worst relative error {worst})")


def _codes(values: list) -> tuple[np.ndarray, list]:
    labels = sorted(set(values), key=str)
    index = {v: i for i, v in enumerate(labels)}
    return np.array([index[v] for v in values]), labels


def _iso(d: date) -> str:
    return d.isoformat()


class Generator:
    def __init__(self, targets: dict, calibration: dict, plan: dict, params: dict,
                 matrices: dict[str, np.ndarray], snapshot: date, seed: int = cfg.SEED):
        self.t = targets
        self.cal = calibration
        self.plan = plan
        self.params = params
        self.matrices = matrices
        self.snapshot = snapshot
        self.rng = np.random.default_rng(seed)
        self.flag_rng = np.random.default_rng([seed, cfg.FLAG_STREAM])  # A30 draws only
        self.grades = list(params["master_scale"]["grades"])
        self.n = len(self.grades)
        self._lifetime: dict[tuple[str, int], np.ndarray] = {}

    # --- helpers --------------------------------------------------------------------------------

    def life(self, segment: str, months: int) -> np.ndarray:
        key = (segment, months)
        if key not in self._lifetime:
            self._lifetime[key] = lifetime_pd(self.matrices[segment], months / 12)
        return self._lifetime[key]

    def maturity_months(self, portfolio: str, segment: str) -> int:
        lo, hi = self.t["risk_profiles"][portfolio]["residual_maturity_years"]
        mode = min(max(self.cal["segments"][segment]["reference_life_years"], lo), hi)
        if lo <= 1.0 and self.rng.random() < cfg.ONE_YEAR_SHARE:
            return 12
        years = self.rng.triangular(lo, mode, hi) if hi > lo else lo
        return int(np.clip(round(years * 12), round(lo * 12), round(hi * 12)))

    def origination_rank(self, segment: str, stage: int, rank: int, months: int,
                         rng: np.random.Generator | None = None) -> int | None:
        """An origination grade that puts ``rank`` above the SICR line (stage 1) or on or below it
        (stage 2)."""
        rng = rng if rng is not None else self.rng
        k = self.params["segments"][segment]["sicr_k"]
        life = self.life(segment, months)
        if stage == 1:
            options = [h for h in (rank - 1, rank, rank + 1)
                       if 1 <= h <= self.n and life[rank - 1] < k * life[h - 1] * (1 - cfg.SICR_MARGIN)]
            weights = np.array([0.25 if h != rank else 0.5 for h in options])
            return int(rng.choice(options, p=weights / weights.sum()))
        options = [h for h in range(1, rank)
                   if life[rank - 1] >= k * life[h - 1] * (1 + cfg.SICR_MARGIN)]
        if not options:
            return None
        options.sort(reverse=True)
        if len(options) > 1 and rng.random() < 0.3:
            return options[1]
        return options[0]

    def _flag_only(self, facilities: list[dict]) -> None:
        """A30: in each segment, a share of the S2 facilities is S2 by a qualitative trigger alone.
        They keep their calibrated current grade, take an origination grade that leaves it above
        the SICR line, and carry at least one trigger (``_ensure_trigger``)."""
        by_segment: dict[str, list[dict]] = {}
        for f in facilities:
            if f["ifrs_stage"] == 2:
                by_segment.setdefault(f["segment"], []).append(f)
        for segment in sorted(by_segment):
            s2 = by_segment[segment]
            count = round(cfg.FLAG_ONLY_S2_SHARE * len(s2))
            for i in sorted(self.flag_rng.choice(len(s2), size=count, replace=False)):
                f = s2[int(i)]
                f["_g0"] = self.origination_rank(segment, 1, f["_rank"], f["_months"], self.flag_rng)
                f["_flag_only"] = True

    def _ensure_trigger(self, row: dict) -> None:
        """A flag-only S2 facility that drew no trigger gets one, from the switched-on triggers."""
        settings = self.params["sicr_triggers"]
        enabled = set(settings["enabled"])
        if (("dpd" in enabled and row["dpd"] >= settings["dpd_days"]) or ("watchlist" in enabled and row["watchlist"])
                or ("forborne" in enabled and row["forborne"])):
            return
        mix = {t: w for t, w in cfg.FLAG_ONLY_TRIGGER_MIX.items() if t in settings["enabled"]}
        if not mix:
            raise ValueError("flag-only S2 facilities need at least one switched-on trigger (A30)")
        pick = str(self.flag_rng.choice(list(mix), p=np.array(list(mix.values())) / sum(mix.values())))
        if pick == "dpd":
            row["dpd"] = int(self.flag_rng.integers(settings["dpd_days"], cfg.DEFAULT_DPD))
        else:
            row[pick] = True

    # --- portfolio ------------------------------------------------------------------------------

    def cell_totals(self, portfolio: str, segments: list[str]) -> tuple[dict, dict]:
        """Facility counts and GCA per (segment, stage)."""
        counts_by_stage = self.t["stages"][portfolio]["count"]
        gca_by_stage = {s: self.t["stages"][portfolio]["gca"][s] * MILLION for s in STAGES}
        if len(segments) == 1:
            seg = segments[0]
            return ({seg: dict(counts_by_stage)}, {seg: gca_by_stage})
        shares = {cfg.P06_SUBSEGMENT[k]: v for k, v in self.t["p06_counterparties"].items()}
        counts = {seg: {} for seg in segments}
        for s in STAGES:
            split = largest_remainder(counts_by_stage[s], {seg: shares[seg] for seg in segments})
            for seg in segments:
                counts[seg][s] = split[seg]
        seed = np.array([[max(counts[seg][s], 0) for s in STAGES] for seg in segments], dtype=float)
        total = self.t["portfolios"][portfolio]["gca"] * MILLION
        table = ipf_table(seed, np.array([shares[seg] * total for seg in segments]),
                          np.array([gca_by_stage[s] for s in STAGES]))
        gca = {seg: {s: table[i, j] for j, s in enumerate(STAGES)} for i, seg in enumerate(segments)}
        return counts, gca

    def portfolio(self, portfolio: str) -> tuple[list[dict], list[dict]]:
        design = cfg.DESIGN[portfolio]
        rng = self.rng
        segments = [s for s, c in self.cal["segments"].items() if c["portfolio"] == portfolio]
        counts, cell_gca = self.cell_totals(portfolio, segments)
        countries = self.t["countries"]
        irb = self.t["irb_share"][portfolio]
        sectors = self.t["sectors"].get(portfolio)
        facilities: list[dict] = []
        obligors: list[dict] = []
        for seg in segments:
            for stage in STAGES:
                n = counts[seg][stage]
                if n == 0:
                    continue
                weights = self.plan[seg][stage] if stage < 3 else {self.n + 1: 1.0}
                for rank, ng in largest_remainder(n, weights).items():
                    if ng == 0:
                        continue
                    cell_target = cell_gca[seg][stage] * weights[rank]
                    for size in partition(ng, design["obligor_sizes"], rng):
                        obligor = self._obligor(portfolio, seg, stage, countries, sectors)
                        obligors.append(obligor)
                        for _ in range(size):
                            facilities.append(self._facility(portfolio, seg, stage, rank, obligor,
                                                             cell_target / ng, irb))
        self._ensure_coverage(obligors, "country", list(countries))
        if sectors:
            self._ensure_coverage(obligors, "nace_code", list(sectors))
        self._top_groups(portfolio, obligors, facilities)
        self._rake(portfolio, facilities, cell_gca)
        return facilities, obligors

    def _ensure_coverage(self, obligors: list[dict], field: str, categories: list[str]) -> None:
        """Every category with a target must hold at least one obligor, so raking can reach it."""
        for category in categories:
            if any(o[field] == category for o in obligors):
                continue
            counts: dict[str, int] = {}
            for o in obligors:
                counts[o[field]] = counts.get(o[field], 0) + 1
            donor = max(counts, key=counts.get)
            candidates = [o for o in obligors if o[field] == donor]
            pick = candidates[int(self.rng.integers(len(candidates)))]
            pick[field] = category
            if field == "nace_code":
                pick["principal_activity"] = f"NACE section {category}"

    def _obligor(self, portfolio, seg, stage, countries, sectors) -> dict:
        design = cfg.DESIGN[portfolio]
        rng = self.rng
        country = str(rng.choice(list(countries), p=np.array(list(countries.values()))))
        if portfolio == "P06":
            sector = cfg.P06_SECTOR[seg]
            nace = None
        else:
            sector = design["sector"]
            nace = str(rng.choice(list(sectors), p=np.array(list(sectors.values())))) if sectors else None
        return {
            "obligor_id": None, "group_id": None, "country": country,
            "counterparty_sector": sector, "nace_code": nace,
            "nace_version": self.t["nace_version"] if nace else None,
            "principal_activity": f"NACE section {nace}" if nace else None,
            "sme_flag": bool(rng.random() < design["sme"]),
            "regulatory_default": stage == 3, "_portfolio": portfolio, "_top": False,
        }

    def _facility(self, portfolio, seg, stage, rank, obligor, avg_size, irb) -> dict:
        design = cfg.DESIGN[portfolio]
        rng = self.rng
        products = design["products"]
        if stage == 3:
            product = next(p for p in products if p != "revolver")
        else:
            product = str(rng.choice(list(products), p=np.array(list(products.values()))))
        profiles = design["profiles"][product]
        approach = "IRB" if rng.random() < irb else "STA"
        months = self.maturity_months(portfolio, seg)
        g0 = None
        if stage < 3:
            for _ in range(200):
                g0 = self.origination_rank(seg, stage, rank, months)
                if g0 is not None:
                    break
                months = max(12, int(months * 0.8))
            if g0 is None:
                raise ValueError(f"{seg}: no origination grade makes grade {rank} S2")
        else:
            g0 = int(rng.integers(max(1, self.n - 4), self.n + 1))
        cal = self.cal["segments"][seg]
        lgd_lo, lgd_hi = self.t["risk_profiles"][portfolio]["lgd"]
        mean = (cal["reference_lgd"] - lgd_lo) / (lgd_hi - lgd_lo)
        lgd = lgd_lo + (lgd_hi - lgd_lo) * rng.beta(mean * 8, (1 - mean) * 8)
        rate = float(np.clip(cal["reference_eir"] + rng.normal(0, design["rate_sd"]),
                             0.0025, cal["reference_eir"] * 3))
        classes = design["classes"]
        reg_class = cfg.P06_CLASS[seg] if portfolio == "P06" else classes[approach]
        return {
            "_obligor": obligor, "_size": avg_size * rng.lognormal(0.0, cfg.SIZE_DISPERSION),
            "portfolio": portfolio, "segment": seg, "ifrs_stage": stage, "_rank": rank,
            "_g0": g0, "product": product,
            "repayment_profile": str(rng.choice(list(profiles), p=np.array(list(profiles.values())))),
            "regulatory_approach": approach, "regulatory_class": reg_class,
            "_months": months, "interest_rate": rate,
            "rate_type": "floating" if rng.random() < design["floating"] else "fixed",
            "ttc_lgd": float(lgd),
        }

    def _top_groups(self, portfolio: str, obligors: list[dict], facilities: list[dict]) -> None:
        target = cfg.DESIGN[portfolio].get("top_group_facilities")
        if not target:
            return
        groups = self.t["concentration_top_groups"]["groups"]
        per_obligor: dict[int, int] = {}
        for f in facilities:
            per_obligor[id(f["_obligor"])] = per_obligor.get(id(f["_obligor"]), 0) + 1
        performing = [o for o in obligors if not o["regulatory_default"]]
        order = self.rng.permutation(len(performing))
        chosen, count = [], 0
        for i in order:
            if count >= target:
                break
            chosen.append(performing[i])
            count += per_obligor[id(performing[i])]
        for j, ob in enumerate(chosen):
            ob["_top"] = True
            ob["group_id"] = f"GRP-{portfolio}-TOP{j % groups + 1:02d}"
        for f in facilities:
            if f["_obligor"]["_top"]:
                f["_size"] *= cfg.TOP_GROUP_SIZE_FACTOR

    def _rake(self, portfolio: str, facilities: list[dict], cell_gca: dict) -> None:
        total = self.t["portfolios"][portfolio]["gca"] * MILLION
        x0 = np.array([f["_size"] for f in facilities])
        margins = []
        cells = [(f["segment"], f["ifrs_stage"], f["_rank"]) for f in facilities]
        codes, labels = _codes(cells)
        targets = []
        for seg, stage, rank in labels:
            weights = self.plan[seg][stage] if stage < 3 else {rank: 1.0}
            targets.append(cell_gca[seg][stage] * weights[rank])
        margins.append((codes, np.array(targets)))
        codes, labels = _codes([f["_obligor"]["country"] for f in facilities])
        margins.append((codes, np.array([self.t["countries"][c] * total for c in labels])))
        irb = self.t["irb_share"][portfolio]
        codes, labels = _codes([f["regulatory_approach"] for f in facilities])
        margins.append((codes, np.array([(irb if a == "IRB" else 1 - irb) * total for a in labels])))
        sectors = self.t["sectors"].get(portfolio)
        if sectors and len(sectors) > 1:
            codes, labels = _codes([f["_obligor"]["nace_code"] for f in facilities])
            margins.append((codes, np.array([sectors[s] * total for s in labels])))
        share = self.t["concentration_top_groups"]["share_of_gca"].get(portfolio)
        if share:
            codes, labels = _codes([f["_obligor"]["_top"] for f in facilities])
            margins.append((codes, np.array([(share if top else 1 - share) * total for top in labels])))
        x = rake(x0, margins)
        for f, gca in zip(facilities, x):
            f["gca"] = float(gca)

    # --- the whole book -------------------------------------------------------------------------

    def run(self) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
        all_fac: list[dict] = []
        all_obl: list[dict] = []
        for portfolio in sorted(self.t["portfolios"]):
            fac, obl = self.portfolio(portfolio)
            all_fac += fac
            all_obl += obl
        for i, ob in enumerate(all_obl, start=1):
            ob["obligor_id"] = f"O{i:05d}"
            if ob["group_id"] is None:
                ob["group_id"] = f"GRP-{ob['obligor_id']}"
        self._check_concentration(all_fac)
        self._flag_only(all_fac)
        facilities = self._facility_table(all_fac)
        obligors = self._obligor_table(all_obl)
        commitments = self._commitments(facilities)
        limit = facilities["principal"] + facilities["facility_id"].map(
            commitments.set_index("facility_id")["nominal_undrawn"]).fillna(0.0)
        facilities["contractual_limit"] = limit
        return facilities, obligors, commitments

    def _check_concentration(self, facilities: list[dict]) -> None:
        groups = self.t["concentration_top_groups"]["groups"]
        for portfolio in self.t["concentration_top_groups"]["share_of_gca"]:
            sizes: dict[str, float] = {}
            for f in facilities:
                if f["portfolio"] == portfolio:
                    gid = f["_obligor"]["group_id"]
                    sizes[gid] = sizes.get(gid, 0.0) + f["gca"]
            top = sorted(sizes, key=sizes.get, reverse=True)[:groups]
            if not all("-TOP" in g for g in top):
                raise ValueError(f"{portfolio}: the designated groups are not the {groups} largest")

    def _facility_table(self, facilities: list[dict]) -> pd.DataFrame:
        rng = self.rng
        rows = []
        snap = self.snapshot
        sicr_days = int(self.params["sicr_triggers"]["dpd_days"])  # the 30+ DPD backstop
        if not 2 <= sicr_days < cfg.DEFAULT_DPD:
            raise ValueError(f"O3 draws past-due days below and above the SICR threshold, so dpd_days must "
                             f"be 2 to {cfg.DEFAULT_DPD - 1}; it is {sicr_days}")
        for i, f in enumerate(facilities, start=1):
            stage = f["ifrs_stage"]
            portfolio = f["portfolio"]
            design = cfg.DESIGN[portfolio]
            gca = f["gca"]
            rate = f["interest_rate"]
            months_accrued = rng.uniform(0, cfg.ACCRUED_MONTHS_MAX)
            principal = gca / (1 + rate * months_accrued / 12)
            years_since = rng.uniform(0.5, 10.0)
            origination = snap - timedelta(days=int(years_since * 365.25))
            default_date = None
            if stage == 1:
                stage_entry = origination
            elif stage == 2:
                stage_entry = max(origination, snap - timedelta(days=int(rng.uniform(0, 730))))
            else:
                default_date = snap - timedelta(days=int(rng.uniform(0, 4 * 365)))
                if origination >= default_date:
                    origination = default_date - timedelta(days=365)
                stage_entry = default_date
            if stage == 1:
                dpd = 0 if rng.random() < 0.95 else int(rng.integers(1, sicr_days))
            elif stage == 2:
                dpd = (int(rng.integers(sicr_days, cfg.DEFAULT_DPD)) if rng.random() < 0.3
                       else int(rng.integers(0, sicr_days)))
            else:
                dpd = int(rng.integers(cfg.DEFAULT_DPD, 361))
            collateral = design["collateral"]
            ltv = dscr = None
            if collateral == "cre":
                collateral = str(rng.choice(self.t["collateral_types"][portfolio]))
            if portfolio in ("P01", "P04"):
                lo, hi = self.t["risk_profiles"][portfolio]["ltv"]
                ltv = float(lo + (hi - lo) * rng.beta(2 + stage, 3))
            if portfolio == "P04":
                lo, hi = self.t["risk_profiles"][portfolio]["dscr"]
                dscr = float(lo + (hi - lo) * rng.beta(4, 1 + 2 * stage))
            row = {
                "facility_id": f"F{i:05d}", "obligor_id": f["_obligor"]["obligor_id"],
                "entity_id": cfg.ENTITY, "portfolio": portfolio, "segment": f["segment"],
                "product": f["product"], "ifrs_stage": stage, "poci": False,
                "accounting_category": self.t["accounting_category"], "currency": self.t["currency"],
                "principal": principal, "accrued_interest": gca - principal, "accrued_in_gca": True,
                "gca": gca, "contractual_limit": principal, "interest_rate": rate,
                "rate_type": f["rate_type"], "residual_maturity": f["_months"] / 12,
                "repayment_profile": f["repayment_profile"],
                "regulatory_approach": f["regulatory_approach"],
                "regulatory_class": f["regulatory_class"],
                "current_grade": "D" if stage == 3 else self.grades[f["_rank"] - 1],
                "origination_grade": self.grades[f["_g0"] - 1], "ttc_lgd": f["ttc_lgd"],
                "dpd": dpd, "watchlist": bool(stage == 3 or (stage == 2 and rng.random() < 0.4)),
                "forborne": bool(rng.random() < (0.0 if stage == 1 else 0.1 if stage == 2 else 0.3)),
                "credit_status_date": _iso(snap),
                "origination_date": _iso(origination), "stage_entry_date": _iso(stage_entry),
                "default_date": _iso(default_date) if default_date else None,
                "default_date__status": "supplied" if default_date else "not_applicable",
                "collateral_type": collateral,
                "collateral_type__status": "supplied" if collateral else "not_applicable",
                "ltv": ltv, "ltv__status": "supplied" if ltv is not None else "not_applicable",
                "dscr": dscr, "dscr__status": "supplied" if dscr is not None else "not_applicable",
                "snapshot_date": _iso(snap),
            }
            if f.get("_flag_only"):
                self._ensure_trigger(row)
            rows.append(row)
        df = pd.DataFrame(rows)
        df["ltv"] = df["ltv"].astype(float)
        df["dscr"] = df["dscr"].astype(float)
        df["dpd"] = df["dpd"].astype("int64")
        df["ifrs_stage"] = df["ifrs_stage"].astype("int64")
        return df

    def _obligor_table(self, obligors: list[dict]) -> pd.DataFrame:
        rows = []
        for ob in obligors:
            rows.append({
                "obligor_id": ob["obligor_id"], "group_id": ob["group_id"], "entity_id": cfg.ENTITY,
                "country": ob["country"], "counterparty_sector": ob["counterparty_sector"],
                "nace_code": ob["nace_code"],
                "nace_code__status": "supplied" if ob["nace_code"] else "not_applicable",
                "nace_version": ob["nace_version"],
                "nace_version__status": "supplied" if ob["nace_version"] else "not_applicable",
                "principal_activity": ob["principal_activity"],
                "principal_activity__status": "supplied" if ob["principal_activity"] else "not_applicable",
                "sme_flag": ob["sme_flag"], "regulatory_default": ob["regulatory_default"],
                "snapshot_date": _iso(self.snapshot),
            })
        return pd.DataFrame(rows)

    def _commitments(self, facilities: pd.DataFrame) -> pd.DataFrame:
        rows = []
        for portfolio, info in sorted(self.t["portfolios"].items()):
            undrawn = (info["undrawn"] or 0.0) * MILLION
            if undrawn <= 0:
                continue
            lines = facilities[(facilities["portfolio"] == portfolio) & (facilities["product"] == "revolver")]
            raw = lines["gca"].to_numpy() * self.rng.uniform(0.3, 1.5, len(lines))
            amounts = raw / raw.sum() * undrawn
            for fid, amount in zip(lines["facility_id"], amounts):
                rows.append({"facility_id": fid, "nominal_undrawn": float(amount),
                             "accounting_ccf": info["ccf"]})
        df = pd.DataFrame(rows)
        df.insert(0, "commitment_id", [f"C{i:05d}" for i in range(1, len(df) + 1)])
        df["currency"] = self.t["currency"]
        df["ccf_source"] = "SYN-PAR-07 section 5.1 test CCF"
        df["asset_category"] = "not_applicable"
        df["provision_classification"] = "off_balance_loan_commitment"
        df["snapshot_date"] = _iso(self.snapshot)
        return df
