from __future__ import annotations


# Country and territory routes are explicit so public URLs remain stable when
# labels contain spaces, punctuation, accents, or political naming variants.
COUNTRY_ROUTE_SLUGS = {
    "Antigua and Barbuda": "antigua-and-barbuda",
    "Aruba": "aruba",
    "Bahamas": "bahamas",
    "Barbados": "barbados",
    "Belize": "belize",
    "British Virgin Islands": "british-virgin-islands",
    "Cayman Islands": "cayman-islands",
    "Curacao": "curacao",
    "Dominica": "dominica",
    "Dominican Republic": "dominican-republic",
    "Grenada": "grenada",
    "Guyana": "guyana",
    "Haiti": "haiti",
    "Jamaica": "jamaica",
    "Montserrat": "montserrat",
    "Puerto Rico": "puerto-rico",
    "Saint Kitts and Nevis": "saint-kitts-and-nevis",
    "Saint Lucia": "saint-lucia",
    "Saint Vincent and the Grenadines": "saint-vincent-and-the-grenadines",
    "Sint Maarten": "sint-maarten",
    "Suriname": "suriname",
    "Trinidad and Tobago": "trinidad-and-tobago",
    "Turks and Caicos Islands": "turks-and-caicos",
    "United States Virgin Islands": "us-virgin-islands",
}


COUNTRY_ROUTE_DISPLAY_NAMES = {
    "Bahamas": "the Bahamas",
}


def country_route_slug(country: str) -> str:
    try:
        return COUNTRY_ROUTE_SLUGS[country]
    except KeyError as error:
        raise ValueError(
            f"Listed country or territory needs an explicit public route slug: {country!r}"
        ) from error


def country_route_display_name(country: str) -> str:
    return COUNTRY_ROUTE_DISPLAY_NAMES.get(country, country)
