# Bank CSV schema — derived from SBACO aoi_benchmark_0.py and reference sheets.
#
# query_template_bank.csv:
#   Header row with TEMPLATE_HEADERS columns.
#   Each cell value is a search query string containing {placeholder} tokens.
#   Example: "What are the best {service} in {city}?"
#
# value_bank.csv:
#   Header row with VALUE_HEADERS columns.
#   Column names must match placeholder names used in template cells.
#   Example row: service="kayak tours", city="Santa Barbara", ...
#
# build_queries_from_matrix(template_rows, value_rows) expands the full cross-product.

TEMPLATE_HEADERS = [
    "core_service",
    "location_plus",
    "faq",
    "pain_point",
    "long_tail",
    "Itineraries",
    "recource",
]

VALUE_HEADERS = [
    "service",
    "city",
    "brand",
    "landmark",
    "neighborhood",
    "pain_point",
    "vibe",
    "location",
]
