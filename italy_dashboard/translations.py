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
    "nav_education": "Education",
    "nav_labor": "Labor",
    "nav_economy": "Economy",
    "nav_climate": "Climate",
    "home_title": "Italy at a glance",
    "home_subtitle": "Key indicators from ISTAT snapshots. Open a section for detail.",
    "crime_title": "Crime",
    "population_title": "Population & migration",
    "education_title": "Education support",
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
        "Rates divide reported-offender counts by resident-population estimates. "
        "The numerator may include nonresidents, so this is not an individual's "
        "likelihood of offending; foreign-resident denominators are available from 2019."
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
    "kpi_rate_ratio_note": "reported-count rate ratio; not individual likelihood",
    "method_note": (
        "Counts, not rates, unless stated: compare groups only against their "
        "population denominators. Citizenship distinguishes Italian vs foreign "
        "nationals; residence status (regular/irregular) is not part of ISTAT "
        "statistics. Cross-offence sums are not unique-person counts. "
        "Reported numerators may include nonresidents, while denominators are residents."
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
    "dsu_ranking_title": "University scholarships granted",
    "dsu_ranking_sub": "Latest academic year, regional DSU grants (USTAT/MUR)",
    "scholarships_granted": "Scholarships granted",
    "unemployment_title": "Unemployment rate",
    "unemployment_sub": "Selected region vs official national IT series (%)",
    "selected_region": "Selected region",
    "national_avg": "National average",
    "selected_pct": "Selected (%)",
    "national_pct": "National (%)",
    "naspi_title": "NASPI benefit recipients",
    "naspi_sub": "Unemployment-benefit claimants, selected region vs national total (INPS)",
    "selected_count": "Selected",
    "national_count": "National",
    "inflation_title": "Inflation (consumer prices)",
    "inflation_sub": "Mean monthly year-over-year change; complete years only (%)",
    "change_pct": "Change (%)",
    # climate page
    "city": "City",
    # {name} is the selected city, or else the selected region, or else
    # "Italia" — substituted in ClimateState.selected_scope_title. Templated
    # because the entity name is a runtime value (see _format_translation).
    "selected_scope_title": "Selected scope: {name}",
    "across_italy_section": "Across Italy",
    # {city} is the selected city, substituted in
    # ClimateState.city_outside_ranking_note. Templated for the same reason
    # as selected_scope_title.
    "city_outside_ranking": (
        "{city} is not among the top 20 fastest-warming cities, so it isn't highlighted below."
    ),
    "warming_title": "Annual temperature",
    "warming_sub": (
        "Annual mean (thin line), the min-max band each year (shaded), and a "
        "10-year centred rolling average (heavy line). ERA5-Land reanalysis "
        "sampled at the province capital — not a station record."
    ),
    "t_mean": "Mean",
    "t_min": "Min (mean of daily minima)",
    "t_max": "Max (mean of daily maxima)",
    "t_band": "Min-max range",
    "t_rolling": "10-year average",
    "stripes_title": "Anomaly against the 1981-2010 normal",
    "stripes_sub": "Degrees Celsius above or below the city's own 1981-2010 average",
    "grid_title": "Warming stripes across cities",
    "grid_sub": "Fastest-warming capitals, same colour scale in every panel",
    "ranking_title": "Fastest-warming cities",
    "ranking_sub": "Degrees Celsius per decade, ordinary least squares over annual means",
    "thresholds_title": "Hot days, tropical nights and frost days",
    "thresholds_sub": ("Days per year with max >= 30 C, min >= 20 C and min <= 0 C"),
    "hot_days": "Hot days",
    "tropical_nights": "Tropical nights",
    "frost_days": "Frost days",
    "distribution_title": "Distribution of daily maxima",
    # {early_lo}-{early_hi} / {late_lo}-{late_hi} are substituted in
    # ClimateState.distribution_sub / dist_early_label / dist_late_label. The
    # windows are derived per city, so these MUST stay templates: a literal
    # year range here would drift away from the data it labels.
    "distribution_sub": (
        "Share of days per 2 C bucket, {early_lo}-{early_hi} against "
        "{late_lo}-{late_hi} — the record split in half"
    ),
    "dist_early": "{early_lo}-{early_hi}",
    "dist_late": "{late_lo}-{late_hi}",
    "distribution_city_only": (
        "Daily histograms need a single city: the regional mart holds yearly "
        "aggregates, not daily readings. Pick a city above to see it."
    ),
    "anomaly": "Anomaly (C)",
    "degrees_per_decade": "C / decade",
    "no_climate": (
        "No temperature data yet. Run  just refresh-weather  (or  just sample  "
        "for synthetic dev data), then reload."
    ),
    # {capitals} of {capitals_total} / {regions} of {regions_total} / a year span
    # are substituted in ClimateState.coverage_text and ClimateCrimeState.coverage_text.
    "climate_coverage": (
        "Coverage: {capitals} of {capitals_total} capitals, {regions} of "
        "{regions_total} regions; complete years {year_start}-{year_end}; "
        "partial endpoint {partial_endpoint}"
    ),
    # Shown at Italia scope only (ClimateState.is_national_scope). The coverage
    # line above gives the counts; this says what the counts do not — WHICH half
    # of the country is missing. Same job, and the same wording pattern, as
    # cc_coverage_note below.
    "climate_coverage_note": (
        "Italia is an unweighted mean of the capitals covered so far, and the "
        "temperature backfill runs in province-code order, so it fills from the "
        "north: much of the South is still missing and the absolute level reads "
        "colder than Italy's. The anomaly chart is far more robust to this, "
        "because it measures each year against the same cities' own baseline."
    ),
    "climate_partial_endpoint_note": (
        "Latest endpoint {partial_endpoint} is incomplete; climate charts use "
        "complete years through {year_end}."
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
    "cc_coverage_note": (
        "With partial, mostly-northern coverage the confound this page relies on "
        "may not show up yet — a tidy null result below can mean too few, "
        "too-northern regions, not that the confound is gone."
    ),
    "cc_caveat": (
        "Association only. This is an ECOLOGICAL comparison: it is region-level "
        "and says nothing about individuals. It is ANNUAL, while the "
        "heat-aggression literature works at daily and monthly grain. It is "
        "UNDERPOWERED, bounded by ISTAT publishing province-level offenders only "
        "from 2022. The outcome is offender counts, not rates, because population "
        "denominators start in 2019; region fixed effects absorb the population "
        "level but not differential regional growth. No p-values or confidence "
        "intervals are shown: with {clusters} observed region clusters they "
        "would overstate precision."
    ),
    "no_climate_crime": (
        "The crime-climate panel needs both the offenders mart and temperature "
        "data. Run  just refresh  and  just refresh-weather  (or  just sample), "
        "then reload."
    ),
    # 404 page
    "not_found_title": "Page not found",
    "not_found_body": "There is no page at this address. Use the navigation above, or go back home.",
    "not_found_cta": "Back to home",
}

IT: dict[str, str] = {
    "nav_home": "Home",
    "nav_crime": "Criminalità",
    "nav_population": "Popolazione",
    "nav_education": "Istruzione",
    "nav_labor": "Lavoro",
    "nav_economy": "Economia",
    "nav_climate": "Clima",
    "home_title": "L'Italia in sintesi",
    "home_subtitle": "Indicatori chiave dagli snapshot ISTAT. Apri una sezione per i dettagli.",
    "crime_title": "Criminalità",
    "population_title": "Popolazione e migrazioni",
    "education_title": "Sostegno allo studio",
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
        "I tassi dividono i conteggi degli autori denunciati per stime della "
        "popolazione residente. Il numeratore può includere non residenti, quindi "
        "non è la probabilità individuale di commettere reati; i denominatori "
        "sugli stranieri residenti sono disponibili dal 2019."
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
    "kpi_rate_ratio_note": "rapporto tra conteggi, non probabilità individuale",
    "method_note": (
        "Conteggi, non tassi, salvo indicazione: confronta i gruppi solo con i "
        "rispettivi denominatori di popolazione. La cittadinanza distingue "
        "italiani e stranieri; lo status di soggiorno (regolare/irregolare) "
        "non fa parte delle statistiche ISTAT. Le somme tra delitti non contano "
        "persone uniche. I numeratori possono includere non residenti, mentre i "
        "denominatori sono residenti."
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
    "dsu_ranking_title": "Borse di studio universitarie concesse",
    "dsu_ranking_sub": "Ultimo anno accademico, borse DSU regionali (USTAT/MUR)",
    "scholarships_granted": "Borse concesse",
    "unemployment_title": "Tasso di disoccupazione",
    "unemployment_sub": "Regione selezionata vs serie nazionale ufficiale IT (%)",
    "selected_region": "Regione selezionata",
    "national_avg": "Media nazionale",
    "selected_pct": "Selezionata (%)",
    "national_pct": "Nazionale (%)",
    "naspi_title": "Percettori NASPI",
    "naspi_sub": "Beneficiari indennità di disoccupazione, regione selezionata vs totale nazionale (INPS)",
    "selected_count": "Selezionata",
    "national_count": "Nazionale",
    "inflation_title": "Inflazione (prezzi al consumo)",
    "inflation_sub": "Media mensile della variazione annua; solo anni completi (%)",
    "change_pct": "Variazione (%)",
    "city": "Città",
    # Vedi il commento nella tabella EN: {name} è un valore a runtime.
    "selected_scope_title": "Ambito selezionato: {name}",
    "across_italy_section": "In tutta Italia",
    # Vedi il commento nella tabella EN: {city} è un valore a runtime.
    "city_outside_ranking": (
        "{city} non è tra le prime 20 città che si scaldano più in fretta, "
        "quindi non è evidenziata qui sotto."
    ),
    "warming_title": "Temperatura annuale",
    "warming_sub": (
        "Media annuale (linea sottile), la fascia minimo-massimo di ogni anno "
        "(colorata) e una media mobile centrata su 10 anni (linea spessa). "
        "Rianalisi ERA5-Land campionata nel capoluogo — non è una serie da stazione."
    ),
    "t_mean": "Media",
    "t_min": "Minima (media delle minime giornaliere)",
    "t_max": "Massima (media delle massime giornaliere)",
    "t_band": "Intervallo min-max",
    "t_rolling": "Media mobile (10 anni)",
    "stripes_title": "Anomalia rispetto alla norma 1981-2010",
    "stripes_sub": "Gradi Celsius sopra o sotto la media 1981-2010 della città",
    "grid_title": "Strisce del riscaldamento per città",
    "grid_sub": "Capoluoghi che si scaldano più in fretta, stessa scala di colore in ogni pannello",
    "ranking_title": "Città che si scaldano più in fretta",
    "ranking_sub": "Gradi Celsius per decennio, minimi quadrati sulle medie annuali",
    "thresholds_title": "Giorni caldi, notti tropicali e giorni di gelo",
    "thresholds_sub": ("Giorni all'anno con massima >= 30 C, minima >= 20 C e minima <= 0 C"),
    "hot_days": "Giorni caldi",
    "tropical_nights": "Notti tropicali",
    "frost_days": "Giorni di gelo",
    "distribution_title": "Distribuzione delle massime giornaliere",
    # Vedi il commento nella tabella EN: sono template, non stringhe fisse.
    "distribution_sub": (
        "Quota di giorni per intervallo di 2 C, {early_lo}-{early_hi} contro "
        "{late_lo}-{late_hi} — la serie divisa in due metà"
    ),
    "dist_early": "{early_lo}-{early_hi}",
    "dist_late": "{late_lo}-{late_hi}",
    "distribution_city_only": (
        "Gli istogrammi giornalieri richiedono una singola città: il mart "
        "regionale contiene aggregati annuali, non dati giornalieri. "
        "Seleziona una città qui sopra per vederlo."
    ),
    "anomaly": "Anomalia (C)",
    "degrees_per_decade": "C / decennio",
    "no_climate": (
        "Nessun dato di temperatura. Esegui  just refresh-weather  (oppure  just sample  "
        "per dati sintetici di sviluppo), poi ricarica."
    ),
    "climate_coverage": (
        "Copertura: {capitals} di {capitals_total} capoluoghi, {regions} di "
        "{regions_total} regioni; anni completi {year_start}-{year_end}; "
        "endpoint parziale {partial_endpoint}"
    ),
    "climate_coverage_note": (
        "Italia è una media non ponderata dei capoluoghi finora coperti, e il "
        "backfill delle temperature procede in ordine di codice provinciale, "
        "quindi da nord: gran parte del Sud manca ancora e il livello assoluto "
        "risulta più freddo di quello italiano. Il grafico delle anomalie è molto "
        "più robusto: misura ogni anno rispetto alla baseline delle stesse città."
    ),
    "climate_partial_endpoint_note": (
        "L'ultimo endpoint {partial_endpoint} è incompleto; i grafici climatici "
        "usano anni completi fino a {year_end}."
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
    "cc_coverage_note": (
        "Con una copertura parziale e per lo più settentrionale, il fattore "
        "confondente su cui si basa questa pagina potrebbe non emergere ancora: "
        "un risultato nullo qui sotto può significare troppe poche regioni, "
        "troppo a nord, non che il fattore confondente sia scomparso."
    ),
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
        "confidenza: con {clusters} cluster regionali osservati sovrastimerebbero "
        "la precisione."
    ),
    "no_climate_crime": (
        "Il panel clima-criminalità richiede sia il mart degli autori sia i dati "
        "di temperatura. Esegui  just refresh  e  just refresh-weather  (oppure  "
        "just sample), poi ricarica."
    ),
    # pagina 404
    "not_found_title": "Pagina non trovata",
    "not_found_body": "Non esiste una pagina a questo indirizzo. Usa la navigazione qui sopra, oppure torna alla home.",
    "not_found_cta": "Torna alla home",
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
