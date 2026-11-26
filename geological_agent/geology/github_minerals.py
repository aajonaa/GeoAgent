"""Pinned upstream mineral spectroscopy, geochemistry and structural geology.

All numerical kernels are supplied by the named upstream libraries. This module
validates scientific semantics and renders bounded, traceable output artifacts.
"""
import csv
from pathlib import Path

from legacy.ToolsAgent.ToolsFuns.source_contracts import decode, finite
from .collection_contracts import operation, reject


def _json(path, required, optional=()):
    p = Path(path)
    if p.stat().st_size > 4_000_000:
        reject("JSON science input exceeds 4 MB", "resource_limit")
    value = decode(p.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict) or set(value) - set(required) - set(optional) or not set(required) <= set(value):
        reject("Input JSON fields differ from the documented file schema")
    finite(value)
    return value


def _array(value, *, ndim=2, positive=False, nonnegative=False):
    import numpy as np
    # Reject booleans and numeric strings before conversion to floating point.
    def number(x):
        if isinstance(x, list):
            return all(number(y) for y in x)
        return isinstance(x, (int, float)) and not isinstance(x, bool)
    if not isinstance(value, list) or not number(value):
        reject("Measurements must be numeric arrays")
    a = np.asarray(value, dtype=float)
    if a.ndim != ndim or not a.size or not np.isfinite(a).all():
        reject("Measurements require nonempty finite rectangular arrays")
    if a.size > 262144:
        reject("Measurement array exceeds 262,144 values", "resource_limit")
    if positive and (a <= 0).any() or nonnegative and (a < 0).any():
        reject("Measurements violate the declared positive-value constraint")
    return a


def _labels(value, count):
    if (not isinstance(value, list) or len(value) != count or
            any(not isinstance(v, str) or not v.strip() or len(v) > 96 or any(ord(c) < 32 for c in v) for v in value)
            or len(set(value)) != count):
        reject("Labels must be unique nonempty strings, at most 96 characters, matching row count")
    return value


def _waves(value):
    import numpy as np
    a = _array(value, ndim=1, positive=True)
    if not 3 <= len(a) <= 2048 or (np.diff(a) <= 0).any() or a.min() < 100 or a.max() > 30000:
        reject("Wavelengths must strictly increase, with 3..2048 bands in 100..30000 nm")
    return a


def _spectra(data):
    waves = _waves(data["wavelength_nm"])
    values = _array(data["spectra"], nonnegative=True)
    if values.shape[1] != len(waves) or values.shape[0] > 128 or values.max() > 1.5:
        reject("Expect at most 128 spectra aligned to wavelengths, reflectance in [0,1.5]")
    labels = _labels(data["sample_ids"], len(values))
    return waves, values, labels


def _references(data, waves):
    import numpy as np
    rw = _waves(data["reference_wavelength_nm"])
    members = _array(data["reference_spectra"], nonnegative=True)
    if len(rw) != len(waves) or not np.allclose(rw, waves, rtol=0, atol=1e-6):
        reject("Reference and measurement wavelengths must match; resample explicitly before calling")
    if members.shape[1] != len(waves) or not 1 <= len(members) <= 32 or members.max() > 1.5:
        reject("Expect 1..32 reference spectra aligned to wavelengths, reflectance in [0,1.5]")
    if (np.linalg.norm(members, axis=1) <= 1e-12).any():
        reject("Zero reference spectra have no defined spectral angle")
    labels = _labels(data["reference_labels"], len(members))
    if not isinstance(data["reference_source"], str) or not 1 <= len(data["reference_source"].strip()) <= 1000:
        reject("Provide the reference library source; it is a caller declaration, not independent verification")
    return members, labels


def _csv(root, name, headers, rows):
    def safe(value):
        # Keep spreadsheet formula syntax out of labels without changing JSON identity.
        if isinstance(value, str) and value.lstrip().startswith(("=", "+", "-", "@")):
            return "'" + value
        return value
    with (root / name).open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow([safe(v) for v in headers])
        writer.writerows([[safe(v) for v in row] for row in rows])


def _figure():
    from matplotlib.figure import Figure
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    fig = Figure(figsize=(8.4, 5.2), layout="constrained", facecolor="#fafbf7")
    FigureCanvasAgg(fig)
    return fig


def _save(fig, root, name):
    fig.savefig(root / (name + ".png"), dpi=160, metadata={"Software": "GeoAgent; measured inputs, pinned upstream algorithm"})
    fig.savefig(root / (name + ".svg"), metadata={"Date": None})
    fig.clear()


def _heatmap(root, name, values, rows, columns, title, unit):
    fig = _figure()
    ax = fig.add_subplot()
    shown = values[:32]
    image = ax.imshow(shown, aspect="auto", cmap="viridis")
    ax.set_xticks(range(len(columns)), columns, rotation=45, ha="right", fontsize=8)
    ax.set_yticks(range(len(shown)), rows[:32], fontsize=8)
    ax.set_title(title + (" (first 32 samples)" if len(values) > 32 else ""))
    fig.colorbar(image, ax=ax, label=unit)
    _save(fig, root, name)


SPECTRA_FIELDS = ("wavelength_nm", "spectra", "sample_ids")
REFERENCE_FIELDS = ("reference_wavelength_nm", "reference_spectra", "reference_labels", "reference_source")


@operation("GeoSpectralAngleMatch")
def spectral_angle_match(args, output_dir):
    import numpy as np
    from spectral import spectral_angles
    data = _json(args["data_path"], SPECTRA_FIELDS + REFERENCE_FIELDS)
    waves, values, samples = _spectra(data)
    refs, labels = _references(data, waves)
    if (np.linalg.norm(values, axis=1) <= 1e-12).any():
        reject("Zero sample spectra have no defined spectral angle")
    angles = np.degrees(spectral_angles(values[:, None, :], refs)[:, 0, :])
    best = np.argmin(angles, axis=1)
    matches = [labels[i] if angles[j, i] <= args["max_angle_degrees"] else None for j, i in enumerate(best)]
    _csv(output_dir, "spectral-angles.csv", ["sample_id", *labels], [[s, *v] for s, v in zip(samples, angles.tolist())])
    _heatmap(output_dir, "spectral-angles", angles, samples, labels, "Spectral angle to supplied references", "Angle (degrees)")
    return {"sample_ids": samples, "reference_labels": labels, "angles_degrees": angles.tolist(),
            "matches": matches, "max_angle_degrees": args["max_angle_degrees"],
            "reference_source": data["reference_source"], "units": {"angles_degrees": "degree", "spectra": "reflectance"}}


@operation("GeoSpectralContinuumRemoval")
def continuum_removal(args, output_dir):
    import numpy as np
    from spectral.algorithms.continuum import spectral_continuum, remove_continuum
    data = _json(args["data_path"], SPECTRA_FIELDS)
    waves, values, samples = _spectra(data)
    continuum = spectral_continuum(values, waves, mode="convex")
    if (continuum <= 1e-12).any():
        reject("Continuum must be positive at every wavelength")
    removed = remove_continuum(values, waves, mode="convex")
    depths = 1 - removed
    deepest = np.argmax(depths, axis=1)
    _csv(output_dir, "continuum-removed.csv", ["sample_id", *waves.tolist()], [[s, *v] for s, v in zip(samples, removed.tolist())])
    fig = _figure()
    ax = fig.add_subplot()
    for label, row in zip(samples[:8], removed[:8]):
        ax.plot(waves, row, label=label, linewidth=1.5)
    ax.set(xlabel="Wavelength (nm)", ylabel="Continuum-removed reflectance", title="Absorption profiles (up to 8 preview spectra)")
    ax.grid(alpha=.2)
    ax.legend(fontsize=8)
    _save(fig, output_dir, "continuum-removed")
    return {"sample_ids": samples, "wavelength_nm": waves.tolist(), "continuum": continuum.tolist(),
            "continuum_removed": removed.tolist(), "deepest_wavelength_nm": waves[deepest].tolist(),
            "maximum_depth": depths[np.arange(len(samples)), deepest].tolist(),
            "units": {"wavelength_nm": "nm", "continuum": "reflectance", "continuum_removed": "dimensionless", "maximum_depth": "dimensionless"}}


@operation("GeoSpectralLinearUnmix")
def linear_unmix(args, output_dir):
    import numpy as np
    from spectral import unmix
    data = _json(args["data_path"], SPECTRA_FIELDS + REFERENCE_FIELDS)
    waves, values, samples = _spectra(data)
    refs, labels = _references(data, waves)
    if len(refs) > len(waves) or np.linalg.matrix_rank(refs) != len(refs) or np.linalg.cond(refs) > 1e8:
        reject("Endmembers must be linearly independent and well conditioned")
    coefficients = unmix(values[:, None, :], refs)[:, 0, :]
    rmse = np.sqrt(np.mean((coefficients @ refs - values) ** 2, axis=1))
    _csv(output_dir, "unmix-coefficients.csv", ["sample_id", *labels, "rmse_reflectance"], [[s, *v, e] for s, v, e in zip(samples, coefficients.tolist(), rmse.tolist())])
    _heatmap(output_dir, "unmix-coefficients", coefficients, samples, labels, "Unconstrained linear spectral coefficients", "Coefficient (not ore grade)")
    return {"sample_ids": samples, "reference_labels": labels, "coefficients": coefficients.tolist(), "rmse_reflectance": rmse.tolist(),
            "sum_to_one_enforced": False, "nonnegative_enforced": False, "reference_source": data["reference_source"],
            "units": {"coefficients": "dimensionless unconstrained coefficient", "rmse_reflectance": "reflectance"}}


@operation("GeoSpectralAngleMap")
def spectral_angle_map(args, output_dir):
    import numpy as np
    import rasterio
    from spectral import spectral_angles
    from matplotlib.colors import BoundaryNorm, ListedColormap
    from matplotlib import colormaps
    waves = _waves(args["raster_wavelength_nm"])
    library = _json(args["library_path"], REFERENCE_FIELDS)
    refs, labels = _references(library, waves)
    # Accept only local single-file GeoTIFFs; a VRT may contain undeclared URLs or files.
    if Path(args["raster_path"]).suffix.lower() not in (".tif", ".tiff"):
        reject("Raster input must be a single-file GeoTIFF")
    with rasterio.open(args["raster_path"], GEOREF_SOURCES="INTERNAL") as src:
        if src.driver != "GTiff" or src.crs is None or src.count != len(waves):
            reject("GeoTIFF requires explicit CRS and one wavelength per band")
        if src.width * src.height > 262144 or src.width * src.height * src.count > 8_388_608:
            reject("Raster exceeds the bounded 262,144-pixel / 8,388,608-value profile", "resource_limit")
        raw = src.read(masked=True).astype(float)
        calibrated = np.moveaxis(raw.filled(np.nan), 0, -1) * args["reflectance_scale"] + args["reflectance_offset"]
        valid = np.isfinite(calibrated).all(axis=-1)
        profile = {"driver": "GTiff", "height": src.height, "width": src.width, "count": 1,
                   "crs": src.crs, "transform": src.transform, "compress": "deflate"}
        if args.get("quality_mask_path"):
            if Path(args["quality_mask_path"]).suffix.lower() not in (".tif", ".tiff"):
                reject("Quality mask must be a single-file GeoTIFF")
            with rasterio.open(args["quality_mask_path"], GEOREF_SOURCES="INTERNAL") as mask:
                if mask.driver != "GTiff" or mask.count != 1 or mask.shape != src.shape or mask.crs != src.crs or mask.transform != src.transform:
                    reject("Quality mask shape, CRS and affine transform must exactly match")
                m = mask.read(1, masked=True)
                if not np.isin(m.compressed(), [0, 1]).all():
                    reject("Quality mask uses 1=valid, 0=excluded; other values must be NoData")
                valid &= (~np.ma.getmaskarray(m)) & (m.filled(0) == 1)
        if not valid.any():
            reject("No valid reflectance pixels remain", "empty_input")
        v = calibrated[valid]
        if v.min() < 0 or v.max() > 1.5 or (np.linalg.norm(v, axis=1) <= 1e-12).any():
            reject("Valid calibrated pixels must be nonzero reflectance in [0,1.5]")
        best_angles = np.full(valid.shape, -9999., dtype="float32")
        classes = np.zeros(valid.shape, dtype="uint16")
        indices = np.flatnonzero(valid)
        unmatched = 0
        for start in range(0, len(v), 8192):
            block = v[start:start + 8192]
            ang = np.degrees(spectral_angles(block[:, None, :], refs)[:, 0, :])
            nearest = np.argmin(ang, axis=1)
            minimum = ang[np.arange(len(block)), nearest]
            accepted = minimum <= args["max_angle_degrees"]
            at = indices[start:start + len(block)]
            best_angles.ravel()[at] = minimum
            classes.ravel()[at] = np.where(accepted, nearest + 1, 0)
            unmatched += int((~accepted).sum())
        for filename, array, dtype, nodata in [("spectral-classes.tif", classes, "uint16", 0), ("spectral-angle-degrees.tif", best_angles, "float32", -9999.)]:
            with rasterio.open(output_dir / filename, "w", **profile, dtype=dtype, nodata=nodata) as dst:
                dst.write(array, 1)
                dst.update_tags(algorithm="Spectral Python spectral_angles", interpretation="reference similarity, not mineral confirmation or ore grade")
        counts = [int((classes == i + 1).sum()) for i in range(len(labels))]
        _csv(output_dir, "spectral-class-statistics.csv", ["class_id", "reference_label", "matched_pixels"], [(i + 1, s, n) for i, (s, n) in enumerate(zip(labels, counts))])
        fig = _figure()
        ax = fig.add_subplot()
        colors = ["#e6e9e3", *colormaps["turbo"](np.linspace(.08, .92, len(labels))).tolist()]
        cmap = ListedColormap(colors)
        im = ax.imshow(classes, cmap=cmap, norm=BoundaryNorm(np.arange(-.5, len(labels) + 1.5), len(colors)))
        bar = fig.colorbar(im, ax=ax, ticks=range(len(labels) + 1))
        bar.ax.set_yticklabels(["Excluded / unmatched", *labels], fontsize=8)
        ax.set(xlabel="Column", ylabel="Row", title="Spectral reference matches")
        _save(fig, output_dir, "spectral-map")
        return {"width": src.width, "height": src.height, "crs": str(src.crs), "affine": list(src.transform)[:6],
                "reference_labels": labels, "matched_pixels": counts, "valid_pixels": int(valid.sum()),
                "excluded_pixels": int((~valid).sum()), "unmatched_pixels": unmatched,
                "reference_source": library["reference_source"], "units": {"angle": "degree", "pixels": "pixel", "reflectance": "dimensionless"}}


REE = ["La", "Ce", "Pr", "Nd", "Sm", "Eu", "Gd", "Tb", "Dy", "Ho", "Er", "Tm", "Yb", "Lu"]
OXIDES = ["SiO2", "TiO2", "Al2O3", "FeO", "Fe2O3", "MnO", "MgO", "CaO", "Na2O", "K2O", "P2O5", "Cr2O3", "NiO"]


def _chemistry(path, *, extra=(), positive=False):
    data = _json(path, ("sample_ids", "components", "values", "unit") + tuple(extra))
    values = _array(data["values"], positive=positive, nonnegative=True)
    if len(values) > 128 or not 2 <= values.shape[1] <= 32:
        reject("Chemistry profile supports 1..128 samples and 2..32 components")
    names = _labels(data["components"], values.shape[1])
    samples = _labels(data["sample_ids"], len(values))
    if data["unit"] not in ("ppm", "wt_percent"):
        reject("All components must share an explicitly declared ppm or wt_percent unit")
    return data, values, samples, names


@operation("GeoGeochemCLR")
def geochem_clr(args, output_dir):
    from pyrolite.comp.codata import CLR
    data, values, samples, names = _chemistry(args["data_path"], positive=True)
    clr = CLR(values)
    _csv(output_dir, "geochemistry-clr.csv", ["sample_id", *names], [[s, *v] for s, v in zip(samples, clr.tolist())])
    _heatmap(output_dir, "geochemistry-clr", clr, samples, names, "Centered log-ratio geochemistry", "Natural log ratio")
    return {"sample_ids": samples, "components": names, "clr": clr.tolist(), "input_unit": data["unit"],
            "units": {"clr": "dimensionless natural log ratio"}}


@operation("GeoGeochemOxideMoles")
def oxide_moles(args, output_dir):
    import pandas as pd
    import pyrolite.geochem
    from pyrolite.geochem.transform import to_molecular
    data, values, samples, names = _chemistry(args["data_path"])
    if data["unit"] != "wt_percent" or any(n not in OXIDES for n in names) or (values > 100).any() or (values.sum(axis=1) <= 0).any() or (values.sum(axis=1) > 105).any():
        reject("Use supported oxide wt_percent, positive totals up to 105; report FeO and Fe2O3 separately")
    frame = pd.DataFrame(values, columns=names)
    moles = to_molecular(frame, renorm=False).to_numpy()
    mol_percent = to_molecular(frame, renorm=True).to_numpy()
    _csv(output_dir, "oxide-molar-percent.csv", ["sample_id", *names], [[s, *v] for s, v in zip(samples, mol_percent.tolist())])
    _heatmap(output_dir, "oxide-molar-percent", mol_percent, samples, names, "Oxide molar composition", "Molar percent")
    return {"sample_ids": samples, "components": names, "moles_per_100g": moles.tolist(), "mol_percent": mol_percent.tolist(),
            "input_totals_wt_percent": values.sum(axis=1).tolist(), "units": {"moles_per_100g": "mol per 100 g sample", "mol_percent": "mol percent of supplied oxides"}}


@operation("GeoGeochemREEPattern")
def ree_pattern(args, output_dir):
    import numpy as np
    import pandas as pd
    import pyrolite.geochem
    data, values, samples, names = _chemistry(args["data_path"], extra=("reference_values", "reference_source"), positive=True)
    if data["unit"] != "ppm" or any(n not in REE for n in names) or names != [n for n in REE if n in names]:
        reject("REE columns require atomic-number order (excluding Pm), all in ppm")
    ref = _array(data["reference_values"], ndim=1, positive=True)
    if len(ref) != len(names) or not isinstance(data["reference_source"], str) or not 1 <= len(data["reference_source"].strip()) <= 1000:
        reject("Provide aligned positive reference ppm values and a declared source")
    normalized = pd.DataFrame(values, columns=names).pyrochem.normalize_to(ref, units="ppm").to_numpy()
    _csv(output_dir, "ree-normalized.csv", ["sample_id", *names], [[s, *v] for s, v in zip(samples, normalized.tolist())])
    fig = _figure()
    ax = fig.add_subplot()
    for label, row in zip(samples[:8], normalized[:8]):
        ax.plot(names, row, marker="o", markersize=3, label=label)
    ax.set_yscale("log")
    ax.set(ylabel="Sample / supplied reference", title="Normalized rare-earth element patterns (up to 8 samples)")
    ax.grid(alpha=.2)
    ax.legend(fontsize=8)
    _save(fig, output_dir, "ree-normalized")
    eu = None
    if all(n in names for n in ("Sm", "Eu", "Gd")):
        eu = (normalized[:, names.index("Eu")] / np.sqrt(normalized[:, names.index("Sm")] * normalized[:, names.index("Gd")])).tolist()
    return {"sample_ids": samples, "components": names, "normalized": normalized.tolist(), "eu_anomaly": eu,
            "reference_source": data["reference_source"], "units": {"normalized": "dimensionless ratio", "eu_anomaly": "Eu_N / sqrt(Sm_N * Gd_N)"}}


@operation("GeoStereonetAnalysis")
def stereonet_analysis(args, output_dir):
    import numpy as np
    import mplstereonet as ms
    data = _json(args["data_path"], ("strike_degrees", "dip_degrees", "measurement_ids", "convention"))
    strike = _array(data["strike_degrees"], ndim=1)
    dip = _array(data["dip_degrees"], ndim=1)
    if not 3 <= len(strike) <= 500 or len(strike) != len(dip) or data["convention"] != "right_hand_rule" or (strike < 0).any() or (strike >= 360).any() or (dip < 0).any() or (dip > 90).any():
        reject("Require 3..500 right-hand-rule strikes [0,360) and dips [0,90], in degrees")
    labels = _labels(data["measurement_ids"], len(strike))
    plunges, bearings, eigenvalues = ms.eigenvectors(strike.copy(), dip.copy(), measurement="poles")
    fit = None
    if eigenvalues[0] - eigenvalues[1] > max(1e-12, abs(eigenvalues[0]) * 1e-8):
        fitted = ms.fit_pole(strike.copy(), dip.copy(), measurement="poles")
        fit = {"strike_degrees": float(fitted[0]) % 360, "dip_degrees": float(fitted[1])}
    _csv(output_dir, "structural-measurements.csv", ["measurement_id", "strike_RHR_degrees", "dip_degrees"], zip(labels, strike.tolist(), dip.tolist()))
    fig = _figure()
    ax = fig.add_subplot(projection="stereonet")
    ax.plane(strike.copy(), dip.copy(), color="#487766", linewidth=.7, alpha=.25)
    ax.pole(strike.copy(), dip.copy(), "o", color="#154c3c", markersize=4)
    if fit is not None:
        ax.plane(fit["strike_degrees"], fit["dip_degrees"], color="#b35f25", linewidth=2)
    ax.grid(alpha=.2)
    ax.set_title("Lower-hemisphere equal-area stereonet\nRight-hand-rule planes and poles", pad=25)
    _save(fig, output_dir, "structural-stereonet")
    return {"measurement_count": len(labels), "fit_plane": fit, "eigenvalues": eigenvalues.tolist(),
            "eigenvector_plunges_degrees": plunges.tolist(), "eigenvector_bearings_degrees": bearings.tolist(),
            "units": {"orientation": "degree, right-hand-rule; lower hemisphere", "eigenvalues": "dimensionless covariance"}}


@operation("GeoStructuralPlaneIntersection")
def plane_intersection(args):
    import numpy as np
    import mplstereonet as ms
    from mplstereonet.stereonet_math import sph2cart
    s1, d1, s2, d2 = (args[k] for k in ("strike1_degrees", "dip1_degrees", "strike2_degrees", "dip2_degrees"))
    n1, n2 = (np.asarray(sph2cart(*ms.pole(s, d))).ravel() for s, d in ((s1, d1), (s2, d2)))
    if np.linalg.norm(np.cross(n1, n2)) < 1e-8:
        reject("Parallel or coincident planes have no unique intersection direction", "unsupported_conditions")
    plunge, bearing = ms.plane_intersection(s1, d1, s2, d2)
    p = float(plunge[0])
    b = float(bearing[0]) % 360
    return {"plunge_degrees": p, "bearing_degrees": None if abs(p - 90) < 1e-8 else b,
            "units": {"plunge_degrees": "degree downward", "bearing_degrees": "degree clockwise from north; null for vertical line"}}
