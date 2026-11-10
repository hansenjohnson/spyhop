"""Distances from angles below the horizon or the horizontal (Unit = reticle on a sighting).

A sighting's Dist with Unit "reticles-<name>" is a reading, turned into a distance with the platform's
altitude (the observer's eye height on a ship or station, the survey altitude on an aircraft;
the sighting's Altitude, else the survey's Platform altitude) and the entry <name> of the reticles
list (Settings → Dropdowns → Reticles; reticles.csv in the template, locked during a survey), whose
method is one of:

  binoculars    reticle divisions counted down from the horizon. Each division is a fixed angle
                (reticle_deg_per_division, which depends on the binoculars: see PRESETS); the angle
                below the horizontal adds the dip of the horizon, which depends on the height.
  marks         evenly spaced calibrated marks (e.g. on an aircraft's window or struts): the reading is
                the mark number, counted from the horizontal (mark 0), and each mark is a fixed angle
                (deg_per_division) further down, so the angle below the horizontal is n × that angle.
  inclinometer  the angle below the horizontal, in degrees, read directly.

The distance follows Lerczak & Hobbs (1998, Marine Mammal Science 14: 590–599), which allows for the
curvature of the earth (no refraction correction): for eye height h above a sphere of radius R and
an angle θ below the horizontal, the line of sight meets the surface at

    D = (R + h) sin θ − sqrt((R + h)² sin² θ − (2Rh + h²))

and the distance along the surface (used to place the animal) is R·asin(D cos θ / R). A line of
sight at or above the horizon never meets the surface, so there is no distance.
"""
from __future__ import annotations

import math

R = 6371008.8            # m, mean earth radius
FT = 0.3048

METHODS = {"binoculars": "Binocular reticles",
           "marks": "Calibrated marks",
           "inclinometer": "Inclinometer degrees"}

# magnification → (label, degrees per reticle division). These are starting points only: the angle
# of one division depends on the make and model, so check the binoculars' manual or calibrate them.
#   7×, 10×: many marine binoculars have a 10-mil scale (0.01 rad = 0.573° per division)
#   25×: Fujinon 25×150 big-eyes, 0.0771° per division (Kinzey & Gerrodette 2001)
PRESETS = {
    "7": ("7× (0.573°)", 0.5730),
    "10": ("10× (0.573°)", 0.5730),
    "25": ("25× big-eyes (0.0771°)", 0.0771),
    "other": ("Other", None),
}


class ReticleError(ValueError):
    """Why a reading can't be turned into a distance (a message for the user)."""


def dip(h_m: float) -> float:
    """The dip of the horizon below the horizontal, in radians, from height h (m)."""
    return math.acos(R / (R + h_m)) if h_m > 0 else 0.0


def angle_below_horizontal(reading: float, h_m: float, settings: dict) -> float:
    """The angle below the horizontal (radians) for a reading, by the method in settings."""
    method = settings.get("reticle_method") or "binoculars"
    if method == "inclinometer":
        return math.radians(float(reading))
    per = float(settings.get("reticle_deg_per_division") or 0)
    if method == "marks":                     # evenly spaced marks, counted down from the horizontal
        if per <= 0:
            raise ReticleError("Set the degrees between marks in Settings → Dropdowns → Reticles.")
        return math.radians(float(reading) * per)
    per = float(settings.get("reticle_deg_per_division") or 0)
    if per <= 0:
        raise ReticleError("Set the angle of one reticle division in Settings → Dropdowns → Reticles.")
    return dip(h_m) + math.radians(float(reading) * per)


def surface_distance_m(h_m: float, theta: float) -> float:
    """Distance along the surface (m) to where a line of sight θ below the horizontal from height h
    meets it (Lerczak & Hobbs 1998). ReticleError if it doesn't (at or above the horizon)."""
    if h_m <= 0:
        raise ReticleError("The platform altitude must be more than 0 ft.")
    rh = R + h_m
    disc = (rh * math.sin(theta)) ** 2 - (2 * R * h_m + h_m * h_m)
    if theta <= 0 or disc < 0:
        raise ReticleError("That reading is at or above the horizon, so it gives no distance.")
    d = rh * math.sin(theta) - math.sqrt(disc)
    return R * math.asin(min(1.0, d * math.cos(theta) / R))


def distance_m(reading: float, altitude_ft: float, settings: dict) -> float:
    """A sighting's distance (m along the surface) from its reading and the platform altitude (ft)."""
    h = float(altitude_ft) * FT
    return surface_distance_m(h, angle_below_horizontal(float(reading), h, settings))


def reading_for(distance_m_: float, altitude_ft: float, settings: dict) -> float | None:
    """The reading that gives a distance (for a position picked on the map), or None."""
    method = settings.get("reticle_method") or "binoculars"
    h = float(altitude_ft) * FT
    if h <= 0 or distance_m_ <= 0:
        return None
    g = distance_m_ / R                                         # angle at the earth's center
    rh = R + h
    d = math.sqrt(rh * rh + R * R - 2 * R * rh * math.cos(g))   # line of sight
    cos_o = (rh * rh + d * d - R * R) / (2 * rh * d)            # angle at the eye, from straight down
    theta = math.pi / 2 - math.acos(max(-1.0, min(1.0, cos_o)))
    if method == "inclinometer":
        return math.degrees(theta)
    per = float(settings.get("reticle_deg_per_division") or 0)
    if method == "marks":
        return math.degrees(theta) / per if per > 0 else None
    return math.degrees(theta - dip(h)) / per if per > 0 else None


# ------------------------------------------------------------------ the reticles list (0.37)
def settings_for(entry: dict) -> dict:
    """The settings the functions above read, from an entry of the reticles list."""
    try:
        per = float(entry.get("deg_per_division") or 0)
    except ValueError:
        per = 0.0
    return {"reticle_method": (entry.get("method") or "binoculars").strip().lower(), "reticle_deg_per_division": per}
