"""UI translation strings (EN/IT). Data only — no Reflex imports.

UI chrome is fully bilingual; DATA labels (region, crime, offence names) come
from ISTAT as fetched — currently English. Re-fetching with an Italian
Accept-Language would localize those too; parked as a future option.
"""

from __future__ import annotations

EN: dict[str, str] = {
    # navbar / pages
    "nav_home": "Home",
    "nav_crime": "Crime",
    "nav_population": "Population",
    "nav_labor": "Labor",
    "nav_economy": "Economy",
    "nav_climate": "Climate",
    "home_title": "Italy at a glance",
    "home_subtitle": "Key indicators from ISTAT snapshots. Open a section for detail.",
    "crime_title": "Crime",
    "population_title": "Population & migration",
    "labor_title": "Labor market",
    "economy_title": "Economy & prices",
    "climate_title": "Climate",
    # shared
    "view_table": "View as table",
    "year": "Year",
    "value": "Value",
    "region": "Region",
    "province": "Province",
    "no_data": (
        "No data snapshot found. Run  just refresh  (or  just sample  for "
        "synthetic dev data), then reload."
    ),
    "no_mart": (
        "Data mart not built yet. Run  just refresh  (or  just sample), which "
        "rebuilds the dbt marts, then reload."
    ),
    # KPI tiles
    "kpi_crime": "Felony convictions",
    "kpi_crime_note": "latest year, total",
    "kpi_population": "Resident population",
    "kpi_population_note": "latest 1 January",
    "kpi_unemployment": "Unemployment rate",
    "kpi_unemployment_note": "latest year, national rate",
    "kpi_inflation": "Inflation",
    "kpi_inflation_note": "latest annual change",
    # crime page
    "tab_offenders": "Offenders (police reports)",
    "tab_convictions": "Convictions (courts)",
    "explore": "Explore",
    "explore_offenders_sub": (
        "Alleged offenders reported by the police — filter, or split by one "
        "dimension (top 3 groups shown)"
    ),
    "explore_convictions_sub": (
        "Felonies of persons convicted by final judgement — filter, or split "
        "by one dimension (top 3 groups shown)"
    ),
    "crime_dim": "Crime",
    "offence_dim": "Offence",
    "citizenship": "Citizenship",
    "sex": "Sex",
    "age": "Age",
    "indicator": "Indicator",
    "split_by": "Split by",
    "reset_filters": "Reset filters",
    "offenders_over_time": "Offenders over time",
    "convictions_over_time": "Convictions over time",
    "annual_totals_sub": "Annual totals for the current filters",
    "offenders": "Offenders",
    "convictions": "Convictions",
    "by_crime_type": "By type of crime",
    "by_offence_type": "By offence type",
    "latest_year_sub": "Selected year, current filters — top 10",
    "by_region_rate": "Regions compared (per 1,000)",
    "by_region_rate_sub": (
        "All regions, offenders per 1,000 residents of the selected group, "
        "selected year. Population-normalized — denominators exist from 2019."
    ),
    "by_region": "By region",
    "by_region_sub": "Totals by region, selected year, current filters",
    "crime_type": "Type of crime",
    "offence_type": "Offence type",
    "rates_title": "Offenders per 1,000 residents, by citizenship",
    "rates_sub": (
        "Each group divided by its own population — the honest comparison. "
        "Foreign-resident denominators are available from 2019."
    ),
    "italians": "Italians",
    "foreigners": "Foreigners",
    "share_title": "Foreign share of offenders",
    "share_sub": "% of alleged offenders who are foreign nationals",
    "share_label": "Foreign share (%)",
    "kpi_total_offenders": "Offenders",
    "kpi_total_offenders_note": "latest year, current filters",
    "kpi_yoy": "Year-over-year",
    "kpi_yoy_note": "change vs previous year",
    "kpi_foreign_share": "Foreign share",
    "kpi_foreign_share_note": "of offenders, latest year",
    "kpi_rate_ratio": "Rate ratio",
    "kpi_rate_ratio_note": "foreign vs italian per-capita rate",
    "method_note": (
        "Counts, not rates, unless stated: compare groups only against their "
        "population denominators. Citizenship distinguishes Italian vs foreign "
        "nationals; residence status (regular/irregular) is not part of ISTAT "
        "statistics. Cross-crime totals count a person once per crime type."
    ),
    # population / labor / economy pages
    "income_title": "Income vs offender rate (regions)",
    "income_sub": (
        "Each dot is a region: income per capita (x) vs offenders per 1,000 "
        "residents of the group (y). Ecological correlation — region-level "
        "association, not individual behavior."
    ),
    "income_axis": "Income per capita (EUR)",
    "rate_axis": "Offenders per 1,000",
    "corr_italians": "Correlation (Italians)",
    "corr_foreigners": "Correlation (Foreigners)",
    "corr_note": "Pearson r across regions, selected year",
    "income_missing": (
        "Income data not fetched yet: find the dataflow with "
        'just discover "reddito disponibile", set it in registry.yaml, then '
        "just refresh income_regional."
    ),
    "income_caveat": (
        "Interpret with care: income correlates with urbanization, police "
        "presence, and reporting propensity. A regional association is not "
        "evidence about individuals (ecological fallacy)."
    ),
    "residents_title": "Resident population",
    "residents_sub": "Residents on 1 January",
    "residents": "Residents (millions)",
    "foreign_share_title": "Foreign residents share",
    "foreign_share_sub": "Foreign residents as % of resident population",
    "unemployment_title": "Unemployment rate",
    "unemployment_sub": "Selected region vs national average (%)",
    "selected_region": "Selected region",
    "national_avg": "National average",
    "selected_pct": "Selected (%)",
    "national_pct": "National (%)",
    "inflation_title": "Inflation (consumer prices)",
    "inflation_sub": "Annual average change of the general index (%)",
    "change_pct": "Change (%)",
    # climate page
    "city": "City",
    "warming_title": "Annual temperature",
    "warming_sub": (
        "Mean of daily mean, minimum and maximum, per year. ERA5-Land "
        "reanalysis sampled at the province capital — not a station record."
    ),
    "t_mean": "Mean",
    "t_min": "Min (mean of daily minima)",
    "t_max": "Max (mean of daily maxima)",
    "stripes_title": "Anomaly against the 1981-2010 normal",
    "stripes_sub": "Degrees Celsius above or below the city's own 1981-2010 average",
    "ranking_title": "Fastest-warming cities",
    "ranking_sub": "Degrees Celsius per decade, ordinary least squares over annual means",
    "thresholds_title": "Hot days, tropical nights and frost days",
    "thresholds_sub": ("Days per year with max >= 30 C, min >= 20 C and min <= 0 C"),
    "hot_days": "Hot days",
    "tropical_nights": "Tropical nights",
    "frost_days": "Frost days",
    "distribution_title": "Distribution of daily maxima",
    "distribution_sub": "Share of days per 2 C bucket, 1951-1980 against 1996-2025",
    "dist_early": "1951-1980",
    "dist_late": "1996-2025",
    "anomaly": "Anomaly (C)",
    "degrees_per_decade": "C / decade",
    "no_climate": (
        "No temperature data yet. Run  just refresh-weather  (or  just sample  "
        "for synthetic dev data), then reload."
    ),
    "nav_climate_crime": "Climate × Crime",  # noqa: RUF001
    "climate_crime_title": "Summer heat and violent crime",
    "cc_raw_title": "Naive view: raw cross-section",
    "cc_raw_sub": (
        "Every region-year, untransformed: absolute summer temperature against "
        "offender counts. The hotter southern regions sit on the right, so this "
        "mostly recovers that the South is warmer and reports crime differently "
        "— a confound, not a finding."
    ),
    "cc_panel_title": "Panel view: within-region deviation",
    "cc_panel_sub": (
        "Region and year fixed effects removed, so each point is a region's "
        "deviation from its own norm in a year that was unusual nationally."
    ),
    "cc_x_raw": "Summer mean daily max (C)",
    "cc_y_raw": "ln(violent offenders)",
    "cc_x_panel": "Summer max, region and year effects removed (C)",
    "cc_y_panel": "ln(violent offenders), region and year effects removed",
    "cc_stat_raw": "Raw",
    "cc_stat_panel": "Panel",
    "cc_stat_n": "Observations",
    "cc_obs_note": "region-years, shared by both views",
    "cc_caveat": (
        "Association only. This is an ECOLOGICAL comparison: it is region-level "
        "and says nothing about individuals. It is ANNUAL, while the "
        "heat-aggression literature works at daily and monthly grain. It is "
        "UNDERPOWERED, bounded by ISTAT publishing province-level offenders only "
        "from 2022. The outcome is offender counts, not rates, because population "
        "denominators start in 2019; region fixed effects absorb the population "
        "level but not differential regional growth. No p-values or confidence "
        "intervals are shown: with 21 clusters they would overstate precision."
    ),
    "no_climate_crime": (
        "The crime-climate panel needs both the offenders mart and temperature "
        "data. Run  just refresh  and  just refresh-weather  (or  just sample), "
        "then reload."
    ),
}

IT: dict[str, str] = {
    "nav_home": "Home",
    "nav_crime": "Criminalità",
    "nav_population": "Popolazione",
    "nav_labor": "Lavoro",
    "nav_economy": "Economia",
    "nav_climate": "Clima",
    "home_title": "L'Italia in sintesi",
    "home_subtitle": "Indicatori chiave dagli snapshot ISTAT. Apri una sezione per i dettagli.",
    "crime_title": "Criminalità",
    "population_title": "Popolazione e migrazioni",
    "labor_title": "Mercato del lavoro",
    "economy_title": "Economia e prezzi",
    "climate_title": "Clima",
    "view_table": "Vedi come tabella",
    "year": "Anno",
    "province": "Provincia",
    "value": "Valore",
    "region": "Regione",
    "no_data": (
        "Nessuno snapshot dati trovato. Esegui  just refresh  (oppure  just "
        "sample  per dati sintetici di sviluppo), poi ricarica."
    ),
    "no_mart": (
        "Mart dati non ancora costruito. Esegui  just refresh  (o  just "
        "sample), che ricostruisce i mart dbt, poi ricarica."
    ),
    "kpi_crime": "Condanne per delitto",
    "kpi_crime_note": "ultimo anno, totale",
    "kpi_population": "Popolazione residente",
    "kpi_population_note": "ultimo 1° gennaio",
    "kpi_unemployment": "Tasso di disoccupazione",
    "kpi_unemployment_note": "ultimo anno, tasso nazionale",
    "kpi_inflation": "Inflazione",
    "kpi_inflation_note": "ultima variazione annua",
    "tab_offenders": "Denunciati (forze di polizia)",
    "tab_convictions": "Condannati (tribunali)",
    "explore": "Esplora",
    "explore_offenders_sub": (
        "Presunti autori di reato denunciati dalle forze di polizia — filtra, "
        "o suddividi per una dimensione (primi 3 gruppi mostrati)"
    ),
    "explore_convictions_sub": (
        "Delitti di condannati con sentenza definitiva — filtra, o suddividi "
        "per una dimensione (primi 3 gruppi mostrati)"
    ),
    "crime_dim": "Reato",
    "offence_dim": "Delitto",
    "citizenship": "Cittadinanza",
    "sex": "Sesso",
    "age": "Età",
    "indicator": "Indicatore",
    "split_by": "Suddividi per",
    "reset_filters": "Azzera filtri",
    "offenders_over_time": "Denunciati nel tempo",
    "convictions_over_time": "Condanne nel tempo",
    "annual_totals_sub": "Totali annui per i filtri correnti",
    "offenders": "Denunciati",
    "convictions": "Condanne",
    "by_crime_type": "Per tipo di reato",
    "by_offence_type": "Per tipo di delitto",
    "latest_year_sub": "Anno selezionato, filtri correnti — primi 10",
    "by_region_rate": "Regioni a confronto (ogni 1.000)",
    "by_region_rate_sub": (
        "Tutte le regioni, denunciati ogni 1.000 residenti del gruppo "
        "selezionato, anno scelto. Normalizzato per popolazione — "
        "denominatori disponibili dal 2019."
    ),
    "by_region": "Per regione",
    "by_region_sub": "Totali per regione, anno selezionato, filtri correnti",
    "crime_type": "Tipo di reato",
    "offence_type": "Tipo di delitto",
    "rates_title": "Denunciati ogni 1.000 residenti, per cittadinanza",
    "rates_sub": (
        "Ogni gruppo diviso per la propria popolazione — il confronto onesto. "
        "I denominatori sugli stranieri residenti sono disponibili dal 2019."
    ),
    "italians": "Italiani",
    "foreigners": "Stranieri",
    "share_title": "Quota straniera dei denunciati",
    "share_sub": "% di presunti autori di reato con cittadinanza straniera",
    "share_label": "Quota straniera (%)",
    "kpi_total_offenders": "Denunciati",
    "kpi_total_offenders_note": "ultimo anno, filtri correnti",
    "kpi_yoy": "Variazione annua",
    "kpi_yoy_note": "rispetto all'anno precedente",
    "kpi_foreign_share": "Quota straniera",
    "kpi_foreign_share_note": "dei denunciati, ultimo anno",
    "kpi_rate_ratio": "Rapporto tassi",
    "kpi_rate_ratio_note": "tasso pro capite stranieri vs italiani",
    "method_note": (
        "Conteggi, non tassi, salvo indicazione: confronta i gruppi solo con i "
        "rispettivi denominatori di popolazione. La cittadinanza distingue "
        "italiani e stranieri; lo status di soggiorno (regolare/irregolare) "
        "non fa parte delle statistiche ISTAT. I totali tra reati contano una "
        "persona una volta per tipo di reato."
    ),
    "income_title": "Reddito vs tasso di denunciati (regioni)",
    "income_sub": (
        "Ogni punto è una regione: reddito pro capite (x) vs denunciati ogni "
        "1.000 residenti del gruppo (y). Correlazione ecologica — associazione "
        "a livello regionale, non comportamento individuale."
    ),
    "income_axis": "Reddito pro capite (EUR)",
    "rate_axis": "Denunciati ogni 1.000",
    "corr_italians": "Correlazione (Italiani)",
    "corr_foreigners": "Correlazione (Stranieri)",
    "corr_note": "r di Pearson tra regioni, anno selezionato",
    "income_missing": (
        "Dati sul reddito non ancora scaricati: trova il dataflow con "
        'just discover "reddito disponibile", impostalo in registry.yaml, poi '
        "just refresh income_regional."
    ),
    "income_caveat": (
        "Interpretare con cautela: il reddito correla con urbanizzazione, "
        "presenza di polizia e propensione alla denuncia. Un'associazione "
        "regionale non dice nulla sugli individui (fallacia ecologica)."
    ),
    "residents_title": "Popolazione residente",
    "residents_sub": "Residenti al 1° gennaio",
    "residents": "Residenti (milioni)",
    "foreign_share_title": "Quota di residenti stranieri",
    "foreign_share_sub": "Residenti stranieri in % della popolazione residente",
    "unemployment_title": "Tasso di disoccupazione",
    "unemployment_sub": "Regione selezionata vs media nazionale (%)",
    "selected_region": "Regione selezionata",
    "national_avg": "Media nazionale",
    "selected_pct": "Selezionata (%)",
    "national_pct": "Nazionale (%)",
    "inflation_title": "Inflazione (prezzi al consumo)",
    "inflation_sub": "Variazione media annua dell'indice generale (%)",
    "change_pct": "Variazione (%)",
    "city": "Città",
    "warming_title": "Temperatura annuale",
    "warming_sub": (
        "Media delle medie, delle minime e delle massime giornaliere, per anno. "
        "Rianalisi ERA5-Land campionata nel capoluogo — non è una serie da stazione."
    ),
    "t_mean": "Media",
    "t_min": "Minima (media delle minime giornaliere)",
    "t_max": "Massima (media delle massime giornaliere)",
    "stripes_title": "Anomalia rispetto alla norma 1981-2010",
    "stripes_sub": "Gradi Celsius sopra o sotto la media 1981-2010 della città",
    "ranking_title": "Città che si scaldano più in fretta",
    "ranking_sub": "Gradi Celsius per decennio, minimi quadrati sulle medie annuali",
    "thresholds_title": "Giorni caldi, notti tropicali e giorni di gelo",
    "thresholds_sub": ("Giorni all'anno con massima >= 30 C, minima >= 20 C e minima <= 0 C"),
    "hot_days": "Giorni caldi",
    "tropical_nights": "Notti tropicali",
    "frost_days": "Giorni di gelo",
    "distribution_title": "Distribuzione delle massime giornaliere",
    "distribution_sub": "Quota di giorni per intervallo di 2 C, 1951-1980 contro 1996-2025",
    "dist_early": "1951-1980",
    "dist_late": "1996-2025",
    "anomaly": "Anomalia (C)",
    "degrees_per_decade": "C / decennio",
    "no_climate": (
        "Nessun dato di temperatura. Esegui  just refresh-weather  (oppure  just sample  "
        "per dati sintetici di sviluppo), poi ricarica."
    ),
    "nav_climate_crime": "Clima × Criminalità",  # noqa: RUF001
    "climate_crime_title": "Caldo estivo e criminalità violenta",
    "cc_raw_title": "Vista ingenua: sezione trasversale grezza",
    "cc_raw_sub": (
        "Ogni regione-anno, senza trasformazioni: temperatura estiva assoluta "
        "contro il numero di autori. Le regioni del Sud, più calde, stanno a "
        "destra: ritrova soprattutto che il Sud è più caldo e denuncia in modo "
        "diverso, un fattore confondente, non un risultato."
    ),
    "cc_panel_title": "Vista panel: deviazione entro regione",
    "cc_panel_sub": (
        "Effetti fissi di regione e anno rimossi: ogni punto è lo scostamento "
        "di una regione dalla propria norma in un anno anomalo a livello nazionale."
    ),
    "cc_x_raw": "Media estiva delle massime giornaliere (C)",
    "cc_y_raw": "ln(autori di reati violenti)",
    "cc_x_panel": "Massima estiva, al netto degli effetti di regione e anno (C)",
    "cc_y_panel": "ln(autori di reati violenti), al netto degli effetti di regione e anno",
    "cc_stat_raw": "Grezzo",
    "cc_stat_panel": "Panel",
    "cc_stat_n": "Osservazioni",
    "cc_obs_note": "regione-anno, comuni a entrambe le viste",
    "cc_caveat": (
        "Solo associazione. Confronto ECOLOGICO: è a livello regionale e non "
        "dice nulla sugli individui. È ANNUALE, mentre la letteratura su caldo "
        "e aggressività lavora su scala giornaliera e mensile. Ha SCARSA "
        "POTENZA STATISTICA, "
        "limitata dal fatto che ISTAT pubblica gli autori a livello provinciale "
        "solo dal 2022. L'esito è il conteggio degli autori, non un tasso, "
        "perché i denominatori di popolazione partono dal 2019; gli effetti "
        "fissi di regione assorbono il livello della popolazione ma non la "
        "crescita differenziale. Non sono mostrati p-value né intervalli di "
        "confidenza: con 21 cluster sovrastimerebbero la precisione."
    ),
    "no_climate_crime": (
        "Il panel clima-criminalità richiede sia il mart degli autori sia i dati "
        "di temperatura. Esegui  just refresh  e  just refresh-weather  (oppure  "
        "just sample), poi ricarica."
    ),
}

# Split-by choices: canonical keys stored in state, labels shown per language.
SPLIT_LABELS: dict[str, dict[str, str]] = {
    "en": {
        "None": "None",
        "Citizenship": "Citizenship",
        "Sex": "Sex",
        "Age": "Age",
        "Region": "Region",
        "Crime": "Crime",
        "Offence": "Offence",
    },
    "it": {
        "None": "Nessuna",
        "Citizenship": "Cittadinanza",
        "Sex": "Sesso",
        "Age": "Età",
        "Region": "Regione",
        "Crime": "Reato",
        "Offence": "Delitto",
    },
}
# label (any language) -> canonical key
SPLIT_LABEL_TO_KEY: dict[str, str] = {
    label: key for lang in SPLIT_LABELS.values() for key, label in lang.items()
}
