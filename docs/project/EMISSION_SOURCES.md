# Emission and Pollution Sources for the Pattom Project

**Date:** 14 October 2026 · **Status:** the emission part of the project source register (PRD section 8.1, D15). Only these sources supply emission values; a missing value is a gap, not something to fill from elsewhere. Values marked "reported" come from an AI research run (web sources, 14 Oct 2026) and have NOT been checked against the papers. The only items checked by hand are marked "verified".

## 1. Working plan (adopted by the user on 14 Oct 2026; guide pending)
Signal timing changes waiting time, stops and acceleration. It does not change distance. So the emission estimate needs idle time at least. Proposal in two phases:

**Phase 1 (can be done now): fuel and CO2.**
Idle CO2 = idle seconds (from video) x idle fuel rate x fuel carbon factor.
Moving CO2 = distance x ARAI 2007 g/km (constant, so equal across plans).
Limit: this captures the idle effect only. The stop-start and acceleration effect is missing until a speed-based model is added.

**Phase 2 (after the papers below are obtained): CO, HC, NOx, PM.**
Add idle rates from ARAI Annexure IV, and speed or VSP-bin rates (IVE model, scaled to ARAI Table I).

### Idle CO2 rates from sourced inputs (derived)
Inputs: idle fuel use from Kumar et al. 2015 (CSIR-CRRI), reported; fuel carbon factors from WRI/Shakti 2015, reported: petrol 2.27193 kg CO2/L, diesel 2.6444 kg CO2/L. Arithmetic checked by running it; the mL per 10 min values reported for each class convert to the same L/h figures.

| Class | Idle fuel (L/h) | CO2 (kg/h) | CO2 (g/min) | CO2 (g/s) |
|---|---|---|---|---|
| Motorcycle (petrol) | 0.14 | 0.318 | 5.3 | 0.088 |
| Three-wheeler (petrol, 2-stroke) | 0.24 | 0.545 | 9.1 | 0.151 |
| Car (petrol) | 0.60 | 1.363 | 22.7 | 0.379 |
| Car (diesel) | 0.60 | 1.587 | 26.4 | 0.441 |
| Bus (diesel) | 0.90 | 2.380 | 39.7 | 0.661 |

Assumptions to state in the report: fuel type per class is assumed (the video cannot tell petrol from diesel); the CRRI three-wheeler data are 2-stroke petrol from one city and one manufacturer; no idle data for CNG vehicles; CRRI also reports a medium truck at 167 mL per 10 min (about 1.0 L/h, diesel). Treat as estimates, not measurements.

## 2. Papers to obtain (priority order)
| # | Citation | What to take from it | Access | Check status |
|---|---|---|---|---|
| 1 | ARAI for CPCB/MoEF (2007, Rev-4 2008). "Emission Factor development for Indian Vehicles." Report AFL/2006-07/IOCL/Emission Factor Project/Final Rep. | Table I (62 g/km factors, pp. 6-13); Annexure IV (separate Excel file: idle g/min and constant-speed g/min for CO, HC, NOx, CO2) | Ask ARAI or CPCB for Annexure IV. A mirror of the PDF was reported at learning-cleanairasia.org (an ICAP library PDF); confirm it is the right file | Reported |
| 2 | Kumar PVP, Singh A, Sharma N, Chalumuri RS (2015). "Evaluation of Idling Fuel Consumption of Vehicles Across Different Cities." CSIR-CRRI conference paper. | Idle fuel by class, per-class tables | ResearchGate; ask an author | Reported (table bodies were garbled) |
| 3 | Sharma N, Kumar PVP, Dhyani R, Ravisekhar Ch, Ravinder K (2019). "Idling fuel consumption and emissions of air pollutants at selected signalized intersections in Delhi." Journal of Cleaner Production 212:8-21. doi:10.1016/j.jclepro.2018.11.275 | Per-class idle fuel and emission factors, method for signalised junctions (341 vehicles, 11 Delhi intersections) | Elsevier, paywalled; college library | Verified (title, authors, journal, volume, pages, DOI, abstract) |
| 4 | Kumar R, Parida P, Shukla S, Saleh W (2015). "MOVES model for idling emission of signalised junction in developing country." World Journal of Science, Technology and Sustainable Development 12(1):25-38. doi:10.1108/WJSTSD-06-2014-0009 | Idle HC, CO, NOx, CO2 at Ashram Chowk, Delhi | Emerald, paywalled | Reported. The abstract units (mg/m3) look wrong; do not use as rates |
| 5 | Dhyani R, Sharma N, Advani M (2019). WIT Transactions on Ecology and the Environment 236:233-243 (Lodhi Road, Delhi). | Idle CO in g/(h.vehicle) for queue links; an example of feeding idle emissions into a dispersion model | Open (witpress.com) | Reported; read in full by the research run |
| 6 | Barth M et al. (2007). IVE model application in Pune. Transportation Research Record 2038. doi:10.3141/2038-20 | How the IVE VSP-bin model was applied to Indian traffic | Sage, paywalled | Reported |
| 7 | Mahesh S, Ramadurai G, Shiva Nagendra SM (2019). "Real-world emissions of gaseous pollutants from motorcycles on Indian urban arterials." Transportation Research Part D 76:72-84. | Speed- and acceleration-based motorcycle rates (CO, HC, NOx, CO2) | Elsevier, paywalled | Reported |
| 8 | Chowdappa C, Boruah A, Chatterjee P, Pawar DS (2024). "Comparative analysis of real-world vehicular emissions from BS-IV and BS-VI cars in India." Environmental Monitoring and Assessment 196(8):745. doi:10.1007/s10661-024-12895-6 | VSP-bin rates for cars (CO2, NOx) | Springer | Reported |
| 9 | Autorickshaw study, Springer 2023 (PubMed 38044411): "Real-world tailpipe emissions from autorickshaws (3-wheelers) under heterogeneous traffic conditions" (title as reported). | CNG three-wheeler CO, HC, NO in g/s against speed and acceleration | Springer / PubMed | Title NOT confirmed (a search did not find it); look it up by the PubMed number |
| 10 | WRI/Shakti (2015). "India Specific Road Transport Emission Factors." | Fuel CO2 factors; CO2 per km by class | Open (shaktifoundation.in) | Reported |

## 3. Gaps that remain (as reported)
- No open Indian NOx or PM for auto-rickshaws by speed or VSP.
- No public idle CO, HC, NOx or PM rates (ARAI Annexure IV is unpublished; CRRI per-class tables are paywalled).
- No measured idle fuel for CNG vehicles.
- No PM10 against PM2.5 split.
- No Indian CH4 or N2O factors.
- No fuel and vehicle-age mix for Thiruvananthapuram district. Kerala on 31 March 2020: 64.9% two-wheelers, 20.4% cars of the registered stock (Kerala Economic Review 2020, reported). EVs were 12.1% of 2025 new registrations (Kerala MVD via Onmanorama, reported).

## 4. Ambient pollution near Pattom (for T07, context only)
Ambient concentration is not vehicle emission and cannot calibrate the estimates. It can only show whether levels rise and fall with traffic across the hours of the day.
- Nearest continuous station: Plammoodu (Kerala PCB), about 0.4-0.5 km from Pattom by third-party coordinates; the KSPCB head-office address is Plamoodu, Pattom P.O. Check the distance in GIS.
- Second continuous station: Kariavattom (Kerala PCB), about 8 km.
- Manual stations (twice-weekly 24-hour samples for SO2, NO2, PM10): Pettah, SMV School, Cosmopolitan Hospital, Veli. Distances not verified.
- Data: the CPCB CAAQMS portal is the official source for hourly downloads (CPCB pages block automated access, so open it in a browser). aqicn.org and aqi.in mirror the feed but are unvalidated.
- NAAQS 2009 values (24-hour unless stated): PM10 100, PM2.5 60, NO2 80 ug/m3; O3 100 ug/m3 (8-hour); CO 2 mg/m3 (8-hour). Verify against the notification before citing.
- Open question O12: use this or not.
