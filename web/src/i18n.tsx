import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import { inkMuted, inkPrimary } from "./theme";

// EN/IT UI layer, mirroring italy_dashboard/translations.py verbatim.
//
// The REFLEX app keys its dictionary by string-id (`t("crime_title")`); this
// app instead keys by the EXACT English string it renders, so existing JSX
// stays the source of truth and `tr("..." )` is a drop-in wrapper whose EN
// case is a no-op. Every IT value is copied from translations.py -- the same
// wording, highlighted by this task's parity goal -- EXCEPT the handful of
// strings below that exist only in this static app (loading lines, per-card
// empty notes, the "Upcoming" hints on cards Reflex does not draw): those are
// translated in this app's own idiom, consistent with the Reflex set.
//
// DATA labels (region, crime, offence, city names, month abbreviations) come
// from the marts as fetched and are deliberately NOT translated, exactly like
// the Reflex app's docstring says ("DATA labels ... come from ISTAT as
// fetched -- currently English").

export type Lang = "en" | "it";

const STORAGE_KEY = "italy-dashboard-lang";

/** The static app's EN -> IT table. Keyed by the literal string the JSX
 * (or a chart module) renders in English; the look-up is
 * `currentLang === "it" ? IT[en] ?? en : en`. */
export const IT: Record<string, string> = {
  // navbar / pages
  Home: "Home",
  Crime: "Criminalità",
  Population: "Popolazione",
  Education: "Istruzione",
  Climate: "Clima",
  "Climate × Crime": "Clima × Criminalità",
  Labor: "Lavoro",
  Economy: "Economia",
  "Italy at a glance": "L'Italia in sintesi",
  "Key indicators from ISTAT snapshots. Open a section for detail.":
    "Indicatori chiave dagli snapshot ISTAT. Apri una sezione per i dettagli.",
  "Population & migration": "Popolazione e migrazioni",
  "Education support": "Sostegno allo studio",
  "Labor market": "Mercato del lavoro",
  "Economy & prices": "Economia e prezzi",
  "Summer heat and violent crime": "Caldo estivo e criminalità violenta",
  // shared
  "View as table": "Vedi come tabella",
  Year: "Anno",
  Value: "Valore",
  Region: "Regione",
  Province: "Provincia",
  City: "Città",
  // KPI tiles
  "Felony convictions": "Condanne per delitto",
  "latest year, total": "ultimo anno, totale",
  "Resident population": "Popolazione residente",
  "latest 1 January": "ultimo 1° gennaio",
  "Unemployment rate": "Tasso di disoccupazione",
  "latest year, national rate": "ultimo anno, tasso nazionale",
  Inflation: "Inflazione",
  "latest annual change": "ultima variazione annua",
  // static-only chrome (loading / empty states)
  "Loading data…": "Caricamento dati…",
  "Starting the query engine…": "Avvio del motore di query…",
  "No data snapshot found.": "Nessuno snapshot dati trovato.",
  // crime page
  "Offenders (police reports)": "Denunciati (forze di polizia)",
  "Convictions (courts)": "Condannati (tribunali)",
  "Alleged offenders reported by the police. Data through {year}.":
    "Presunti autori di reato denunciati dalle forze di polizia. Dati fino al {year}.",
  "Felonies of persons convicted by final judgement. Data through {year}.":
    "Delitti di condannati con sentenza definitiva. Dati fino al {year}.",
  Explore: "Esplora",
  "Filter, or split by one dimension (top 3 groups shown)":
    "Filtra, o suddividi per una dimensione (primi 3 gruppi mostrati)",
  "Split by": "Suddividi per",
  None: "Nessuna",
  Citizenship: "Cittadinanza",
  Sex: "Sesso",
  Age: "Età",
  Offence: "Delitto",
  Indicator: "Indicatore",
  "Reset filters": "Azzera filtri",
  "Offenders over time": "Denunciati nel tempo",
  "Convictions over time": "Condanne nel tempo",
  "Annual totals for the current filters": "Totali annui per i filtri correnti",
  Offenders: "Denunciati",
  Convictions: "Condanne",
  "Year-over-year": "Variazione annua",
  "change vs previous year": "rispetto all'anno precedente",
  "Foreign share": "Quota straniera",
  "of offenders, latest year": "dei denunciati, ultimo anno",
  "Rate ratio": "Rapporto tassi",
  "reported-count rate ratio; not individual likelihood":
    "rapporto tra conteggi denunciati, non probabilità individuale",
  "latest year, current filters": "ultimo anno, filtri correnti",
  "Offenders per 1,000 residents, by citizenship":
    "Denunciati ogni 1.000 residenti, per cittadinanza",
  "Rates divide reported-offender counts by resident-population estimates. The numerator may include nonresidents, so this is not an individual's likelihood of offending; foreign-resident denominators are available from 2019.":
    "I tassi dividono i conteggi degli autori denunciati per stime della popolazione residente. Il numeratore può includere non residenti, quindi non è la probabilità individuale di commettere reati; i denominatori sugli stranieri residenti sono disponibili dal 2019.",
  "Regions compared (per 1,000)": "Regioni a confronto (ogni 1.000)",
  "All regions, offenders per 1,000 residents of the selected group, selected year. Population-normalized -- denominators exist from 2019.":
    "Tutte le regioni, denunciati ogni 1.000 residenti del gruppo selezionato, anno scelto. Normalizzato per popolazione — denominatori disponibili dal 2019.",
  "Foreign share of offenders": "Quota straniera dei denunciati",
  "% of alleged offenders who are foreign nationals":
    "% di presunti autori di reato con cittadinanza straniera",
  "By type of crime": "Per tipo di reato",
  "Selected year, current filters -- top 10 (same year as above)":
    "Anno selezionato, filtri correnti — primi 10 (stesso anno di cui sopra)",
  "By offence type": "Per tipo di delitto",
  "Selected year, current filters -- top 10":
    "Anno selezionato, filtri correnti — primi 10",
  "By region": "Per regione",
  "Totals by region, selected year, current filters (same year as above)":
    "Totali per regione, anno selezionato, filtri correnti (stesso anno di cui sopra)",
  Italians: "Italiani",
  Foreigners: "Stranieri",
  "Offenders per 1,000 residents": "Denunciati ogni 1.000 residenti",
  "Offenders per 1,000": "Denunciati ogni 1.000",
  "Foreign share (%)": "Quota straniera (%)",
  "Type of crime": "Tipo di reato",
  "Offence type": "Tipo di delitto",
  "No data for the current filters.": "Nessun dato per i filtri correnti.",
  "this year": "quest'anno",
  "No rate data for this selection.":
    "Nessun dato sui tassi per questa selezione.",
  "No ranking data for {year}.": "Nessun dato per la classifica per {year}.",
  "No share data for this selection.":
    "Nessun dato sulla quota per questa selezione.",
  "No breakdown data for {year}.": "Nessun dato di dettaglio per {year}.",
  "No regional data for {year}.": "Nessun dato regionale per {year}.",
  "Data mart not built yet. Run  just refresh  (or  just sample), which rebuilds the dbt marts, then reload.":
    "Mart dati non ancora costruito. Esegui  just refresh  (o  just sample), che ricostruisce i mart dbt, poi ricarica.",
  "Counts, not rates, unless stated: compare groups only against their population denominators. Citizenship distinguishes Italian vs foreign nationals; residence status (regular/irregular) is not part of ISTAT statistics. Cross-offence sums are not unique-person counts. Reported numerators may include nonresidents, while denominators are residents.":
    "Conteggi, non tassi, salvo indicazione: confronta i gruppi solo con i rispettivi denominatori di popolazione. La cittadinanza distingue italiani e stranieri; lo status di soggiorno (regolare/irregolare) non fa parte delle statistiche ISTAT. Le somme tra delitti non contano persone uniche. I numeratori possono includere non residenti, mentre i denominatori sono residenti.",
  // income card
  "Income vs offender rate (regions)":
    "Reddito vs tasso di denunciati (regioni)",
  "Each dot is a region: income per capita (x) vs offenders per 1,000 residents of the group (y). Ecological correlation -- region-level association, not individual behavior.":
    "Ogni punto è una regione: reddito pro capite (x) vs denunciati ogni 1.000 residenti del gruppo (y). Correlazione ecologica — associazione a livello regionale, non comportamento individuale.",
  "Income per capita (EUR)": "Reddito pro capite (EUR)",
  "Correlation (Italians)": "Correlazione (Italiani)",
  "Correlation (Foreigners)": "Correlazione (Stranieri)",
  "No income/rate data for {year}.": "Nessun dato reddito/tasso per {year}.",
  'Income data not fetched yet: find the dataflow with just discover "reddito disponibile", set it in registry.yaml, then just refresh income_regional.':
    'Dati sul reddito non ancora scaricati: trova il dataflow con just discover "reddito disponibile", impostalo in registry.yaml, poi just refresh income_regional.',
  "Interpret with care: income correlates with urbanization, police presence, and reporting propensity. A regional association is not evidence about individuals (ecological fallacy).":
    "Interpretare con cautela: il reddito correla con urbanizzazione, presenza di polizia e propensione alla denuncia. Un'associazione regionale non dice nulla sugli individui (fallacia ecologica).",
  // population / labor / economy pages
  "Residents on 1 January": "Residenti al 1° gennaio",
  "Residents (millions)": "Residenti (milioni)",
  "Foreign residents share": "Quota di residenti stranieri",
  "Foreign residents as % of resident population":
    "Residenti stranieri in % della popolazione residente",
  "University scholarships granted": "Borse di studio universitarie concesse",
  "Latest academic year, regional DSU grants (USTAT/MUR)":
    "Ultimo anno accademico, borse DSU regionali (USTAT/MUR)",
  "DSU scholarship mart not built yet.":
    "Il mart delle borse DSU non è ancora stato creato.",
  "Scholarships granted": "Borse concesse",
  "Selected region vs official national IT series (%)":
    "Regione selezionata vs serie nazionale ufficiale IT (%)",
  "Selected region": "Regione selezionata",
  "National average": "Media nazionale",
  "Unemployment rate (%)": "Tasso di disoccupazione (%)",
  "Selected (%)": "Selezionata (%)",
  "National (%)": "Nazionale (%)",
  "NASPI benefit recipients": "Percettori NASPI",
  "Unemployment-benefit claimants, selected region vs national total (INPS)":
    "Beneficiari indennità di disoccupazione, regione selezionata vs totale nazionale (INPS)",
  Recipients: "Percettori",
  Selected: "Selezionata",
  National: "Nazionale",
  "No population data for {region}.":
    "Nessun dato sulla popolazione per {region}.",
  "No unemployment data for {region}.":
    "Nessun dato sulla disoccupazione per {region}.",
  "No foreign-share data for {region}.":
    "Nessun dato sulla quota straniera per {region}.",
  "Inflation (consumer prices)": "Inflazione (prezzi al consumo)",
  "Mean monthly year-over-year change; complete years only (%)":
    "Media mensile della variazione annua; solo anni completi (%)",
  "Change (%)": "Variazione (%)",
  "No inflation data.": "Nessun dato sull'inflazione.",
  // climate page
  "Selected scope: {name}": "Ambito selezionato: {name}",
  "Across Italy": "In tutta Italia",
  "Annual temperature": "Temperatura annuale",
  "Annual mean (thin line), the min-max band each year (shaded), and a 10-year centred rolling average (heavy line).":
    "Media annuale (linea sottile), la fascia minimo-massimo di ogni anno (colorata) e una media mobile centrata su 10 anni (linea spessa).",
  "Min (mean of daily minima)": "Minima (media delle minime giornaliere)",
  Mean: "Media",
  "Max (mean of daily maxima)": "Massima (media delle massime giornaliere)",
  "Anomaly against the 1981-2010 normal":
    "Anomalia rispetto alla norma 1981-2010",
  "Degrees Celsius above or below the own 1981-2010 average.":
    "Gradi Celsius sopra o sotto la media 1981-2010 della città.",
  "Hot days, tropical nights and frost days":
    "Giorni caldi, notti tropicali e giorni di gelo",
  "Days per year with max ≥ 30°C, min ≥ 20°C and min ≤ 0°C.":
    "Giorni all'anno con massima ≥ 30°C, minima ≥ 20°C e minima ≤ 0°C.",
  "Hot days": "Giorni caldi",
  "Tropical nights": "Notti tropicali",
  "Frost days": "Giorni di gelo",
  Precipitation: "Precipitazioni",
  "Annual total (bars) and a 10-year centred rolling average (line). ERA5-Land reanalysis grid-cell precipitation at the province capital, not rain-gauge data: good for year-to-year swings and long-run change, not for local records.":
    "Totale annuo (barre) e media mobile centrata su 10 anni (linea). Precipitazione della cella di rianalisi ERA5-Land sul capoluogo, non dati da pluviometro: adatta alle oscillazioni tra un anno e l'altro e ai cambiamenti di lungo periodo, non ai record locali.",
  "Total (mm)": "Totale (mm)",
  "Wet days (≥ 1 mm)": "Giorni piovosi (≥ 1 mm)",
  "vs 1981-2010 (%)": "Rispetto al 1981-2010 (%)",
  "10-year average (mm)": "Media mobile 10 anni (mm)",
  "No precipitation data for {name} in this snapshot.":
    "Nessun dato di precipitazione per {name} in questa versione dei dati.",
  "Distribution of daily maxima": "Distribuzione delle massime giornaliere",
  "Share of days per 2°C bucket, the city's record split into an early and a late window.":
    "Quota di giorni per intervallo di 2°C, la serie della città divisa in una finestra iniziale e una finale.",
  "Daily histograms need a single city: the regional mart holds yearly aggregates, not daily readings. Pick a city above to see it.":
    "Gli istogrammi giornalieri richiedono una singola città: il mart regionale contiene aggregati annuali, non dati giornalieri. Seleziona una città qui sopra per vederlo.",
  "Month-by-month anomaly": "Anomalia mese per mese",
  "Each cell is one month's anomaly against 1981-2010; unobserved months are left blank, not zero.":
    "Ogni cella è l'anomalia di un mese rispetto a 1981-2010; i mesi non osservati sono lasciati vuoti, non a zero.",
  "No annual temperature data for {name}.":
    "Nessun dato sulla temperatura annuale per {name}.",
  "No anomaly data for {name}.": "Nessun dato sulle anomalie per {name}.",
  "No threshold-day data for {name}.":
    "Nessun dato sui giorni soglia per {name}.",
  "Daily temperature data isn't included in this build, so the distribution chart isn't available for any city.":
    "I dati giornalieri di temperatura non sono inclusi in questa build, quindi il grafico della distribuzione non è disponibile per nessuna città.",
  "Couldn't load the daily-maxima distribution for {name} just now. Reloading the page may help.":
    "Impossibile caricare la distribuzione delle massime giornaliere per {name} in questo momento. Ricaricare la pagina può aiutare.",
  "{name} doesn't have two complete years of daily data to compare yet.":
    "{name} non ha ancora due anni completi di dati giornalieri da confrontare.",
  "The month-by-month grid needs a single city too — pick one above to see it.":
    "Anche la griglia mese per mese richiede una singola città — selezionane una qui sopra per vederla.",
  "No monthly data for {name}.": "Nessun dato mensile per {name}.",
  "No grid data.": "Nessun dato per la griglia.",
  "No ranking data.": "Nessun dato per la classifica.",
  "No temperature data yet. Run ": "Nessun dato di temperatura. Esegui ",
  "(or ": "(oppure ",
  " for synthetic dev data), then reload.":
    " per dati sintetici di sviluppo), poi ricarica.",
  "Fastest-warming cities": "Città che si scaldano più in fretta",
  "Degrees Celsius per decade, ordinary least squares over annual means. Not filtered by the selection above — the selected city (if any) is outlined instead.":
    "Gradi Celsius per decennio, minimi quadrati sulle medie annuali. Non filtrato dalla selezione qui sopra — la città selezionata (se presente) è invece evidenziata con un contorno.",
  "Warming stripes across cities": "Strisce del riscaldamento per città",
  "Fastest-warming capitals, same colour scale in every panel. Not filtered by the selection above — the selected city's panel (if present) is ringed instead.":
    "Capoluoghi che si scaldano più in fretta, stessa scala di colore in ogni pannello. Non filtrato dalla selezione qui sopra — il pannello della città selezionata (se presente) è invece cerchiato.",
  "{name} is not among the top 20 fastest-warming cities, so it isn't highlighted below.":
    "{name} non è tra le prime 20 città che si scaldano più in fretta, quindi non è evidenziata qui sotto.",
  "{region} here means {covered} of {total} capitals covered so far, not the whole region: the rest of {region} has no temperature data in this snapshot yet.":
    "Qui {region} significa {covered} di {total} capoluoghi coperti finora, non tutta la regione: il resto di {region} non ha ancora dati di temperatura in questo snapshot.",
  "Coverage: {capitals} of {capitals_total} capitals, {regions} of {regions_total} regions; complete years {year_start}-{year_end}; partial endpoint {partial_endpoint}":
    "Copertura: {capitals} di {capitals_total} capoluoghi, {regions} di {regions_total} regioni; anni completi {year_start}-{year_end}; endpoint parziale {partial_endpoint}",
  "Latest endpoint {partial_endpoint} is incomplete; climate charts use complete years through {year_end}.":
    "L'ultimo endpoint {partial_endpoint} è incompleto; i grafici climatici usano anni completi fino a {year_end}.",
  "Italia is an unweighted mean of the capitals covered so far, and the temperature backfill runs in province-code order, so it fills from the north: much of the South is still missing and the absolute level reads colder than Italy's. The anomaly chart is far more robust to this, because it measures each year against the same cities' own baseline.":
    "Italia è una media non ponderata dei capoluoghi finora coperti, e il backfill delle temperature procede in ordine di codice provinciale, quindi da nord: gran parte del Sud manca ancora e il livello assoluto risulta più freddo di quello italiano. Il grafico delle anomalie è molto più robusto: misura ogni anno rispetto alla baseline delle stesse città.",
  "Anomaly (°C)": "Anomalia (°C)",
  "°C / decade": "°C / decennio",
  "{v}°C / decade": "{v}°C / decennio",
  // climate chart axes / tips (charts/climate.tsx)
  "Temperature (°C)": "Temperatura (°C)",
  "Daily max (°C)": "Massima giornaliera (°C)",
  "Share of days (%)": "Quota di giorni (%)",
  "Days / year": "Giorni / anno",
  "n/a": "n.d.",
  "Mean: {v}": "Media: {v}",
  "Range: {v1} to {v2}": "Intervallo: da {v1} a {v2}",
  "10-yr average: {v}": "Media mobile (10 anni): {v}",
  "Precipitation (mm)": "Precipitazioni (mm)",
  "Total: {v}": "Totale: {v}",
  "Wet days (≥ 1 mm): {v}": "Giorni piovosi (≥ 1 mm): {v}",
  "{value} vs 1981-2010": "{value} rispetto alla norma 1981-2010",
  "{t} daily max": "{t} massima giornaliera",
  "{label}: {v}% of days": "{label}: {v}% dei giorni",
  // climate x crime page
  "Naive view: raw cross-section": "Vista ingenua: sezione trasversale grezza",
  "Every region-year, untransformed: absolute summer temperature against offender counts. The hotter southern regions sit on the right, so this mostly recovers that the South is warmer and reports crime differently — a confound, not a finding.":
    "Ogni regione-anno, senza trasformazioni: temperatura estiva assoluta contro il numero di autori. Le regioni del Sud, più calde, stanno a destra: ritrova soprattutto che il Sud è più caldo e denuncia in modo diverso, un fattore confondente, non un risultato.",
  "Panel view: within-region deviation":
    "Vista panel: deviazione entro regione",
  "Region and year fixed effects removed, so each point is a region's deviation from its own norm in a year that was unusual nationally.":
    "Effetti fissi di regione e anno rimossi: ogni punto è lo scostamento di una regione dalla propria norma in un anno anomalo a livello nazionale.",
  "Summer mean daily max (C)": "Media estiva delle massime giornaliere (C)",
  "ln(violent offenders)": "ln(autori di reati violenti)",
  "Summer max, region and year effects removed (C)":
    "Massima estiva, al netto degli effetti di regione e anno (C)",
  "ln(violent offenders), region and year effects removed":
    "ln(autori di reati violenti), al netto degli effetti di regione e anno",
  Raw: "Grezzo",
  Panel: "Panel",
  Observations: "Osservazioni",
  "region-years, shared by both views":
    "regione-anno, comuni a entrambe le viste",
  "No region-year observations.": "Nessuna osservazione regione-anno.",
  "Association only. This is an ECOLOGICAL comparison: it is region-level and says nothing about individuals. It is ANNUAL, while the heat-aggression literature works at daily and monthly grain. It is UNDERPOWERED, bounded by ISTAT publishing province-level offenders only from 2022. The outcome is offender counts, not rates, because population denominators start in 2019; region fixed effects absorb the population level but not differential regional growth. No p-values or confidence intervals are shown: with 21 clusters they would overstate precision.":
    "Solo associazione. Confronto ECOLOGICO: è a livello regionale e non dice nulla sugli individui. È ANNUALE, mentre la letteratura su caldo e aggressività lavora su scala giornaliera e mensile. Ha SCARSA POTENZA STATISTICA, limitata dal fatto che ISTAT pubblica gli autori a livello provinciale solo dal 2022. L'esito è il conteggio degli autori, non un tasso, perché i denominatori di popolazione partono dal 2019; gli effetti fissi di regione assorbono il livello della popolazione ma non la crescita differenziale. Non sono mostrati p-value né intervalli di confidenza: con 21 cluster sovrastimerebbero la precisione.",
  "With partial, mostly-northern coverage the confound this page relies on may not show up yet — a tidy null result below can mean too few, too-northern regions, not that the confound is gone.":
    "Con una copertura parziale e per lo più settentrionale, il fattore confondente su cui si basa questa pagina potrebbe non emergere ancora: un risultato nullo qui sotto può significare troppe poche regioni, troppo a nord, non che il fattore confondente sia scomparso.",
  "The crime-climate panel needs both the offenders mart and temperature data. Run  just refresh  and  just refresh-weather  (or  just sample), then reload.":
    "Il panel clima-criminalità richiede sia il mart degli autori sia i dati di temperatura. Esegui  just refresh  e  just refresh-weather  (oppure  just sample), poi ricarica.",
  // 404 page
  "Page not found": "Pagina non trovata",
  "There is no page at “#/{slug}”. Use the navigation above, or go back home.":
    "Non esiste una pagina a “#/{slug}”. Usa la navigazione qui sopra, oppure torna alla home.",
  "Back to home": "Torna alla home",
};

// -- module-level language, read synchronously by `tr()` from anywhere
// (including chart spec helpers that never touch React). Kept in sync with
// the React context by `LangProvider` on every render; the initial value is
// decided at module load so the very first paint never needs an effect.
let currentLang: Lang = readInitialLang();

function readInitialLang(): Lang {
  const stored = window.localStorage.getItem(STORAGE_KEY);
  if (stored === "en" || stored === "it") return stored;
  // User's pick: browser-language default, Italian first. Matches nothing in
  // the Reflex default (which is plain "en") but was requested for this app.
  return /^it\b/i.test(window.navigator.language) ? "it" : "en";
}

/** Translate an English string (used verbatim in the JSX / chart modules) to
 * the current language. Falls back to the English input when a string has no
 * IT entry -- the deliberate behaviour for the handful of static-only bits
 * (see the module docstring). */
export function tr(en: string): string {
  if (currentLang !== "it") return en;
  return IT[en] ?? en;
}

/** `tr` + `{name}`-style substitution in one step (`Selected scope: {name}`
 * -> `Ambito selezionato: Roma`). Placeholder keys use the same names the
 * Reflex translations.py templates use, so values are dropped in without
 * language-specific branching. */
export function trt(
  template: string,
  values: Record<string, string | number | null | undefined>,
): string {
  return tr(template).replace(/\{(\w+)\}/g, (_m, k: string) =>
    values[k] === undefined || values[k] === null ? "" : String(values[k]),
  );
}

// -- React binding ----------------------------------------------------------

interface LangContextValue {
  lang: Lang;
  setLang: (lang: Lang) => void;
}

const LangContext = createContext<LangContextValue>({
  lang: readInitialLang(),
  setLang: () => undefined,
});

/** Language provider + localStorage persistence. Syncs the module-level
 * `currentLang` on every render (BEFORE any child builds chart specs in its
 * own render, since the provider renders before its children), and persists
 * every change so a reload keeps the choice. */
export function LangProvider({ children }: { children: ReactNode }) {
  const [lang, setLang] = useState<Lang>(currentLang);

  const handleSetLang = useCallback((next: Lang) => {
    setLang(next);
    window.localStorage.setItem(STORAGE_KEY, next);
  }, []);

  // Render-phase, not effect-phase: chart specs memoised on `lang` must
  // already read the new language when they rebuild in this same commit.
  const value = useMemo(() => {
    currentLang = lang;
    return { lang, setLang: handleSetLang };
  }, [lang, handleSetLang]);

  return <LangContext.Provider value={value}>{children}</LangContext.Provider>;
}

/** Subscribe to the current language -- also re-renders this component on a
 * change, which is what lets `tr()` strings throughout it swap. */
export function useLang(): LangContextValue {
  return useContext(LangContext);
}

/** The EN · IT toggle, mirroring components.py's `_lang_toggle`: the active
 * chip is bold + primary ink, the inactive one muted. */
export function LangToggle() {
  const { lang, setLang } = useLang();

  const chip = (code: Lang, label: string) => (
    <span
      role="button"
      aria-pressed={lang === code}
      onClick={() => setLang(code)}
      style={{
        cursor: "pointer",
        fontSize: "0.85em",
        fontWeight: lang === code ? 700 : 400,
        color: lang === code ? inkPrimary() : inkMuted(),
        userSelect: "none",
      }}
    >
      {label}
    </span>
  );

  return (
    <span
      style={{ display: "inline-flex", alignItems: "center", gap: "0.4rem" }}
    >
      {chip("en", "EN")}·{chip("it", "IT")}
    </span>
  );
}
