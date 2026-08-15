"""App entry point: routes + per-page on_load handlers."""

import reflex as rx

from italy_dashboard.pages.climate import climate_page
from italy_dashboard.pages.climate_crime import climate_crime_page
from italy_dashboard.pages.crime import crime_page
from italy_dashboard.pages.economy import economy_page
from italy_dashboard.pages.home import home_page
from italy_dashboard.pages.labor import labor_page
from italy_dashboard.pages.population import population_page
from italy_dashboard.state import (
    ClimateCrimeState,
    ClimateState,
    CrimeState,
    EconomyState,
    HomeState,
    LaborState,
    OffendersState,
    PopulationState,
)

app = rx.App()

app.add_page(home_page, route="/", title="Italy Dashboard", on_load=HomeState.load)
app.add_page(
    crime_page,
    route="/crime",
    title="Crime · Italy Dashboard",
    on_load=[OffendersState.load, CrimeState.load],
)
app.add_page(
    population_page,
    route="/population",
    title="Population · Italy Dashboard",
    on_load=PopulationState.load,
)
app.add_page(labor_page, route="/labor", title="Labor · Italy Dashboard", on_load=LaborState.load)
app.add_page(
    economy_page, route="/economy", title="Economy · Italy Dashboard", on_load=EconomyState.load
)
app.add_page(
    climate_page, route="/climate", title="Climate · Italy Dashboard", on_load=ClimateState.load
)
app.add_page(
    climate_crime_page,
    route="/climate-crime",
    title="Climate × Crime · Italy Dashboard",  # noqa: RUF001
    on_load=ClimateCrimeState.load,
)
