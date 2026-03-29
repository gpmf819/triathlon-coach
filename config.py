# ============================================================================
# config.py — Central configuration for Triathlon Coach 2.0
# ============================================================================
#
# This is the ONLY place you need to edit when:
#   - Your FTP or LTHR changes (after a ramp test)
#   - The race date changes
#   - Your weekly schedule changes
#   - You want to add/remove workouts from the library
#
# Everything else in the system reads from here.
# ============================================================================

from datetime import date

# ─── ATHLETE ────────────────────────────────────────────────────────────────

ATHLETE_NAME        = "Gaël"
ATHLETE_WEIGHT_KG   = 75

# ─── PERFORMANCE CONSTANTS ──────────────────────────────────────────────────
# Update these after each ramp test / threshold test.

FTP_WATTS           = 291           # Bike FTP (watts) — ramp test confirmed
BIKE_LTHR           = 172           # Bike lactate threshold HR (bpm)
RUN_LTHR            = 172           # Run lactate threshold HR (bpm)
MAX_HR              = 190           # Maximum heart rate (bpm)
SWIM_THRESHOLD_PACE = "2:00/100m"  # CSS (Critical Swim Speed) threshold pace

# ─── RACE ───────────────────────────────────────────────────────────────────

RACE_DATE   = date(2026, 6, 20)    # Tremblant 5150 Olympic distance
RACE_NAME   = "Tremblant 5150"
CTL_TARGET  = 48                   # Target CTL at race day (Olympic distance)

# ─── SCHEDULE CONSTRAINTS ───────────────────────────────────────────────────
# What sports are permitted on each day of the week.
# The weekly planner will only assign workouts that match these constraints.
# "long_bike" and "long_run" are treated as distinct sport slots for Saturday/Sunday.
# "brick" is allowed in place of "long_bike" once we enter the final 6 weeks.

SCHEDULE = {
    "monday":    {"allowed_sports": ["run", "bike"],         "notes": ""},
    "tuesday":   {"allowed_sports": ["run", "bike"],         "notes": ""},
    "wednesday": {"allowed_sports": ["swim"],                "notes": "Swim only"},
    "thursday":  {"allowed_sports": ["run", "bike"],         "notes": ""},
    "friday":    {"allowed_sports": ["run", "bike"],         "notes": ""},
    "saturday":  {"allowed_sports": ["long_bike", "brick"],  "notes": "Long bike; brick in final 6 weeks"},
    "sunday":    {"allowed_sports": ["long_run"],            "notes": "Long aerobic run"},
}

# ─── WORKOUT LIBRARY ────────────────────────────────────────────────────────
# All 41 named workouts available to the weekly planner.
#
# Fields:
#   name          — display name used in Intervals.icu and WhatsApp messages
#   zwo_file      — filename in triathlon-coach_workouts/ (None = text-based)
#   sport         — "bike", "run", or "swim"
#   day_types     — which Day-Type labels this workout can fill
#                   (see DAY_TYPE_RULES below for the full taxonomy)
#   intensity     — "recovery", "z2_endurance", "tempo_sweetspot",
#                   "threshold", or "vo2max"
#   est_tss       — estimated Training Stress Score for load calculations
#   duration_min  — estimated total duration in minutes
#   description   — one-line description for the WhatsApp plan summary
#   phase_ok      — training phases this workout is appropriate for
#                   ("all", "base", "build", "peak", "taper")
#   race_specific — True = only use in final 6 weeks (RACE-SPECIFIC day type)

WORKOUT_LIBRARY = [

    # ── BIKE: CoachChris Zwift Sessions ──────────────────────────────────────

    {
        "name": "CoachChris Gimenez #01",
        "zwo_file": "CoachChris ''Gimenez'' #01.zwo",
        "sport": "bike",
        "day_types": ["Z2 ENDURANCE"],
        "intensity": "z2_endurance",
        "est_tss": 65,
        "duration_min": 90,
        "description": "Classic 90-min Z2 endurance ride. Steady aerobic base.",
        "phase_ok": ["all"],
        "race_specific": False,
    },
    {
        "name": "CoachChris Gimenez #02",
        "zwo_file": "CoachChris ''Gimenez'' #02.zwo",
        "sport": "bike",
        "day_types": ["Z2 ENDURANCE"],
        "intensity": "z2_endurance",
        "est_tss": 70,
        "duration_min": 95,
        "description": "Z2 endurance variation, slightly longer than #01.",
        "phase_ok": ["all"],
        "race_specific": False,
    },
    {
        "name": "CoachChris Tempo-Force",
        "zwo_file": "CoachChris Tempo-Force - avec 8 x 6 min en force 65-75 RPM - 2hrs z-2.zwo",
        "sport": "bike",
        "day_types": ["Z2 ENDURANCE", "QUALITY"],
        "intensity": "z2_endurance",
        "est_tss": 85,
        "duration_min": 120,
        "description": "2-hr Z2 base ride with 8×6-min force efforts at 65–75 RPM. Neuromuscular strength without intensity.",
        "phase_ok": ["base", "build"],
        "race_specific": False,
    },
    {
        "name": "CoachChris Power Cycling Enduro #02",
        "zwo_file": "CoachChris Power Cycling Enduro #02.zwo",
        "sport": "bike",
        "day_types": ["LONG AEROBIC"],
        "intensity": "z2_endurance",
        "est_tss": 90,
        "duration_min": 120,
        "description": "Long aerobic power endurance ride at Z2 intensity.",
        "phase_ok": ["all"],
        "race_specific": False,
    },
    {
        "name": "CoachChris Power Cycling Enduro #03",
        "zwo_file": "CoachChris Power Cycling Enduro #03.zwo",
        "sport": "bike",
        "day_types": ["LONG AEROBIC"],
        "intensity": "z2_endurance",
        "est_tss": 95,
        "duration_min": 125,
        "description": "Long aerobic power endurance ride, slightly longer than #02.",
        "phase_ok": ["all"],
        "race_specific": False,
    },
    {
        "name": "CoachChris Power Cycling Enduro #04",
        "zwo_file": "CoachChris Power Cycling Enduro #04.zwo",
        "sport": "bike",
        "day_types": ["LONG AEROBIC"],
        "intensity": "z2_endurance",
        "est_tss": 100,
        "duration_min": 130,
        "description": "Longest aerobic power endurance ride — peak long aerobic bike volume.",
        "phase_ok": ["build", "peak"],
        "race_specific": False,
    },
    {
        "name": "CoachChris PACING Prog #01",
        "zwo_file": "CoachChris PACING Prog #01.zwo",
        "sport": "bike",
        "day_types": ["QUALITY"],
        "intensity": "tempo_sweetspot",
        "est_tss": 75,
        "duration_min": 75,
        "description": "Pacing progression workout — builds to tempo/sweet spot. Teaches even-effort pacing discipline.",
        "phase_ok": ["base", "build"],
        "race_specific": False,
    },
    {
        "name": "CoachChris Tempo #00",
        "zwo_file": "CoachChris Tempo#00.zwo",
        "sport": "bike",
        "day_types": ["QUALITY"],
        "intensity": "tempo_sweetspot",
        "est_tss": 72,
        "duration_min": 70,
        "description": "Introductory tempo ride with sweet spot intervals. Good entry-level quality session.",
        "phase_ok": ["base", "build"],
        "race_specific": False,
    },
    {
        "name": "CoachChris Tempo #01",
        "zwo_file": "CoachChris Tempo#01.zwo",
        "sport": "bike",
        "day_types": ["QUALITY"],
        "intensity": "tempo_sweetspot",
        "est_tss": 78,
        "duration_min": 75,
        "description": "Tempo sweet spot progression, slightly harder than #00.",
        "phase_ok": ["base", "build"],
        "race_specific": False,
    },
    {
        "name": "CoachChris Tempo #02",
        "zwo_file": "CoachChris Tempo#02.zwo",
        "sport": "bike",
        "day_types": ["QUALITY"],
        "intensity": "tempo_sweetspot",
        "est_tss": 82,
        "duration_min": 80,
        "description": "Tempo sweet spot with extended intervals.",
        "phase_ok": ["base", "build"],
        "race_specific": False,
    },
    {
        "name": "CoachChris Tempo #05",
        "zwo_file": "CoachChris Tempo#05.zwo",
        "sport": "bike",
        "day_types": ["QUALITY"],
        "intensity": "tempo_sweetspot",
        "est_tss": 88,
        "duration_min": 85,
        "description": "Progressive tempo session — sustained sweet spot efforts, higher volume.",
        "phase_ok": ["build", "peak"],
        "race_specific": False,
    },
    {
        "name": "CoachChris Tempo #08",
        "zwo_file": "CoachChris Tempo#08.zwo",
        "sport": "bike",
        "day_types": ["QUALITY"],
        "intensity": "tempo_sweetspot",
        "est_tss": 92,
        "duration_min": 90,
        "description": "Advanced tempo session — long sweet spot intervals, high-volume quality.",
        "phase_ok": ["build", "peak"],
        "race_specific": False,
    },
    {
        "name": "CoachChris FTK-13",
        "zwo_file": "CoachChris FTK-13.zwo",
        "sport": "bike",
        "day_types": ["QUALITY"],
        "intensity": "threshold",
        "est_tss": 85,
        "duration_min": 75,
        "description": "Threshold intervals near FTP — classic lactate threshold development.",
        "phase_ok": ["build", "peak"],
        "race_specific": False,
    },
    {
        "name": "CoachChris FTK-14",
        "zwo_file": "CoachChris FTK-14.zwo",
        "sport": "bike",
        "day_types": ["QUALITY"],
        "intensity": "threshold",
        "est_tss": 90,
        "duration_min": 80,
        "description": "Extended threshold session — harder and longer than FTK-13.",
        "phase_ok": ["build", "peak"],
        "race_specific": False,
    },
    {
        "name": "CoachChris PAM00 z-5",
        "zwo_file": "CoachChris PAM00 z-5.zwo",
        "sport": "bike",
        "day_types": ["QUALITY"],
        "intensity": "vo2max",
        "est_tss": 80,
        "duration_min": 70,
        "description": "VO2max intervals — entry PAM session, 3×(6×30sec at 105% FTP).",
        "phase_ok": ["build", "peak"],
        "race_specific": False,
    },
    {
        "name": "CoachChris PAM01 z-5",
        "zwo_file": "CoachChris PAM01 z-5.zwo",
        "sport": "bike",
        "day_types": ["QUALITY"],
        "intensity": "vo2max",
        "est_tss": 82,
        "duration_min": 72,
        "description": "VO2max PAM series — second session.",
        "phase_ok": ["build", "peak"],
        "race_specific": False,
    },
    {
        "name": "CoachChris PAM02 z-5",
        "zwo_file": "CoachChris PAM02 z-5.zwo",
        "sport": "bike",
        "day_types": ["QUALITY"],
        "intensity": "vo2max",
        "est_tss": 84,
        "duration_min": 75,
        "description": "VO2max PAM series — third session.",
        "phase_ok": ["build", "peak"],
        "race_specific": False,
    },
    {
        "name": "CoachChris PAM03 z-5",
        "zwo_file": "CoachChris PAM03 z-5.zwo",
        "sport": "bike",
        "day_types": ["QUALITY"],
        "intensity": "vo2max",
        "est_tss": 86,
        "duration_min": 77,
        "description": "VO2max PAM series — fourth session.",
        "phase_ok": ["build", "peak"],
        "race_specific": False,
    },
    {
        "name": "CoachChris PAM05 z-5",
        "zwo_file": "CoachChris PAM05 z-5.zwo",
        "sport": "bike",
        "day_types": ["QUALITY"],
        "intensity": "vo2max",
        "est_tss": 88,
        "duration_min": 80,
        "description": "VO2max PAM series — advanced session.",
        "phase_ok": ["peak"],
        "race_specific": False,
    },
    {
        "name": "CoachChris PAM06 z-5",
        "zwo_file": "CoachChris PAM06 z-5.zwo",
        "sport": "bike",
        "day_types": ["QUALITY"],
        "intensity": "vo2max",
        "est_tss": 90,
        "duration_min": 82,
        "description": "VO2max PAM series — advanced session.",
        "phase_ok": ["peak"],
        "race_specific": False,
    },
    {
        "name": "CoachChris PAM07 z-5",
        "zwo_file": "CoachChris PAM07 z-5.zwo",
        "sport": "bike",
        "day_types": ["QUALITY"],
        "intensity": "vo2max",
        "est_tss": 92,
        "duration_min": 85,
        "description": "VO2max PAM series — peak difficulty.",
        "phase_ok": ["peak"],
        "race_specific": False,
    },

    # ── BIKE: Norwegian Method ────────────────────────────────────────────────

    {
        "name": "NOR Bike — Sweet Spot 2×20",
        "zwo_file": "NOR_Bike_SweetSpot_2x20.zwo",
        "sport": "bike",
        "day_types": ["QUALITY"],
        "intensity": "tempo_sweetspot",
        "est_tss": 80,
        "duration_min": 75,
        "description": "2×20 min sweet spot at 88–93% FTP. Foundational threshold development.",
        "phase_ok": ["base", "build"],
        "race_specific": False,
    },
    {
        "name": "NOR Bike — Sweet Spot 3×15",
        "zwo_file": "NOR_Bike_SweetSpot_3x15.zwo",
        "sport": "bike",
        "day_types": ["QUALITY"],
        "intensity": "tempo_sweetspot",
        "est_tss": 82,
        "duration_min": 78,
        "description": "3×15 min sweet spot. More repeats, shorter efforts than 2×20.",
        "phase_ok": ["base", "build"],
        "race_specific": False,
    },
    {
        "name": "NOR Bike — 5×10 Threshold",
        "zwo_file": "NOR_Bike_Main_5x10.zwo",
        "sport": "bike",
        "day_types": ["QUALITY"],
        "intensity": "threshold",
        "est_tss": 92,
        "duration_min": 85,
        "description": "Norwegian main session: 5×10 min at 87–92% FTP, 2.5 min recovery. 50 min total threshold work.",
        "phase_ok": ["build", "peak"],
        "race_specific": False,
    },
    {
        "name": "NOR Bike — 4×8 Midweek",
        "zwo_file": "NOR_Bike_MidWeek_4x8.zwo",
        "sport": "bike",
        "day_types": ["QUALITY"],
        "intensity": "threshold",
        "est_tss": 82,
        "duration_min": 75,
        "description": "Midweek threshold: 4×8 min. Shorter version of the main session.",
        "phase_ok": ["build", "peak"],
        "race_specific": False,
    },
    {
        "name": "NOR Bike — Over-Under 3×12",
        "zwo_file": "NOR_Bike_OverUnder_3x12.zwo",
        "sport": "bike",
        "day_types": ["QUALITY"],
        "intensity": "threshold",
        "est_tss": 88,
        "duration_min": 80,
        "description": "Over-under intervals 3×12 min, alternating above and below threshold. Trains lactate buffering.",
        "phase_ok": ["build", "peak"],
        "race_specific": False,
    },
    {
        "name": "NOR Bike — Threshold Progression 3×15",
        "zwo_file": "NOR_Bike_ThresholdProgression_3x15.zwo",
        "sport": "bike",
        "day_types": ["QUALITY"],
        "intensity": "threshold",
        "est_tss": 90,
        "duration_min": 85,
        "description": "3×15 min threshold progression — each interval slightly harder. Teaches pacing under fatigue.",
        "phase_ok": ["build", "peak"],
        "race_specific": False,
    },
    {
        "name": "NOR Bike — Low Cadence Muscular Tension",
        "zwo_file": "NOR_Bike_LowCadence_MuscTension.zwo",
        "sport": "bike",
        "day_types": ["QUALITY"],
        "intensity": "tempo_sweetspot",
        "est_tss": 78,
        "duration_min": 70,
        "description": "Muscular tension intervals at 50–60 RPM. Builds power application and neuromuscular strength.",
        "phase_ok": ["base", "build"],
        "race_specific": False,
    },
    {
        "name": "NOR Bike — VO2max 4×4",
        "zwo_file": "NOR_Bike_VO2max_4x4.zwo",
        "sport": "bike",
        "day_types": ["QUALITY"],
        "intensity": "vo2max",
        "est_tss": 85,
        "duration_min": 75,
        "description": "4×4 min VO2max intervals. Maximum aerobic power, classic Norwegian high-intensity block.",
        "phase_ok": ["build", "peak"],
        "race_specific": False,
    },
    {
        "name": "NOR Bike — VO2max 30/30",
        "zwo_file": "NOR_Bike_VO2max_30_30.zwo",
        "sport": "bike",
        "day_types": ["QUALITY"],
        "intensity": "vo2max",
        "est_tss": 82,
        "duration_min": 70,
        "description": "30-on/30-off VO2max microbursts. High volume of VO2 stimulus without long single efforts.",
        "phase_ok": ["build", "peak"],
        "race_specific": False,
    },
    {
        "name": "NOR Bike — Race Sim Olympic",
        "zwo_file": "NOR_Bike_RaceSim_Olympic.zwo",
        "sport": "bike",
        "day_types": ["RACE-SPECIFIC"],
        "intensity": "threshold",
        "est_tss": 95,
        "duration_min": 90,
        "description": "Olympic distance bike race simulation — sustained threshold power with race surges. Final 6 weeks only.",
        "phase_ok": ["peak"],
        "race_specific": True,
    },
    {
        "name": "NOR Brick — Bike + Run",
        "zwo_file": "NOR_Brick_BikeRun.zwo",
        "sport": "bike",
        "day_types": ["RACE-SPECIFIC"],
        "intensity": "threshold",
        "est_tss": 100,
        "duration_min": 100,
        "description": "Brick: bike threshold effort followed immediately by a short run. Trains T2 transition legs.",
        "phase_ok": ["peak"],
        "race_specific": True,
    },

    # ── RUN: Norwegian Method ─────────────────────────────────────────────────

    {
        "name": "NOR Run — Easy Zone 1",
        "zwo_file": "NOR_Run_Easy_Zone1.zwo",
        "sport": "run",
        "day_types": ["RECOVERY", "Z2 ENDURANCE"],
        "intensity": "recovery",
        "est_tss": 35,
        "duration_min": 40,
        "description": "Easy Zone 1 recovery run. HR below 140. Genuine aerobic base.",
        "phase_ok": ["all"],
        "race_specific": False,
    },
    {
        "name": "NOR Run — Long Negative Split",
        "zwo_file": "NOR_Run_Long_NegativeSplit.zwo",
        "sport": "run",
        "day_types": ["LONG AEROBIC"],
        "intensity": "z2_endurance",
        "est_tss": 85,
        "duration_min": 100,
        "description": "Long aerobic run with negative split — second half slightly faster. Builds fat oxidation and pacing discipline.",
        "phase_ok": ["all"],
        "race_specific": False,
    },
    {
        "name": "NOR Run — Strides Neuromuscular",
        "zwo_file": "NOR_Run_Strides_Neuromuscular.zwo",
        "sport": "run",
        "day_types": ["Z2 ENDURANCE"],
        "intensity": "z2_endurance",
        "est_tss": 45,
        "duration_min": 50,
        "description": "Easy run with 6–8 acceleration strides at the end. Maintains leg speed without cumulative fatigue.",
        "phase_ok": ["all"],
        "race_specific": False,
    },
    {
        "name": "NOR Run — Tempo 3×12",
        "zwo_file": "NOR_Run_Tempo_3x12.zwo",
        "sport": "run",
        "day_types": ["QUALITY"],
        "intensity": "tempo_sweetspot",
        "est_tss": 72,
        "duration_min": 75,
        "description": "Tempo cruise intervals: 3×12 min at 82–87% threshold (HR 155–163). 36 min total tempo work.",
        "phase_ok": ["base", "build"],
        "race_specific": False,
    },
    {
        "name": "NOR Run — 5×6 Threshold",
        "zwo_file": "NOR_Run_5x6_Threshold.zwo",
        "sport": "run",
        "day_types": ["QUALITY"],
        "intensity": "threshold",
        "est_tss": 78,
        "duration_min": 70,
        "description": "Main threshold run: 5×6 min at threshold pace (HR 163–172). The Norwegian core run session.",
        "phase_ok": ["build", "peak"],
        "race_specific": False,
    },
    {
        "name": "NOR Run — VO2max 7×3",
        "zwo_file": "NOR_Run_VO2max_7x3.zwo",
        "sport": "run",
        "day_types": ["QUALITY"],
        "intensity": "vo2max",
        "est_tss": 80,
        "duration_min": 65,
        "description": "VO2max run: 7×3 min at 95–100% max aerobic pace. Maximum aerobic power development.",
        "phase_ok": ["build", "peak"],
        "race_specific": False,
    },
    {
        "name": "NOR Run — Race Pace 5×8",
        "zwo_file": "NOR_Run_RacePace_5x8.zwo",
        "sport": "run",
        "day_types": ["RACE-SPECIFIC"],
        "intensity": "threshold",
        "est_tss": 82,
        "duration_min": 75,
        "description": "Olympic race pace run: 5×8 min at 10km race pace. Specific to Tremblant run leg.",
        "phase_ok": ["peak"],
        "race_specific": True,
    },
    {
        "name": "NOR Run — Pre-Race Opener",
        "zwo_file": "NOR_Run_PreRace_Opener.zwo",
        "sport": "run",
        "day_types": ["RACE-SPECIFIC"],
        "intensity": "tempo_sweetspot",
        "est_tss": 40,
        "duration_min": 35,
        "description": "Short pre-race activation: easy jog + priming strides. Race week only.",
        "phase_ok": ["taper"],
        "race_specific": True,
    },
    {
        "name": "NOR Run — Brick Off Bike",
        "zwo_file": "NOR_Run_Brick_OffBike.zwo",
        "sport": "run",
        "day_types": ["RACE-SPECIFIC"],
        "intensity": "tempo_sweetspot",
        "est_tss": 45,
        "duration_min": 25,
        "description": "Short T2 brick run immediately off the bike. 20–25 min at Olympic race pace. Trains jelly-leg transition.",
        "phase_ok": ["peak"],
        "race_specific": True,
    },
]

# ─── PERIODIZATION ───────────────────────────────────────────────────────────
# Season phases with CTL and TSS targets per week.
# This is the single source of truth — intervals_client.py will be updated
# to import from here rather than duplicating this data.

PERIODIZATION = [
    {"phase": "Base 1",    "start": "2026-03-21", "end": "2026-03-27", "ctl_target": (25, 30), "tss_target": (260, 290)},
    {"phase": "Base 2",    "start": "2026-03-28", "end": "2026-04-10", "ctl_target": (30, 35), "tss_target": (290, 320)},
    {"phase": "Late Base", "start": "2026-04-11", "end": "2026-04-24", "ctl_target": (35, 40), "tss_target": (320, 350)},
    {"phase": "Build 1",   "start": "2026-04-25", "end": "2026-05-08", "ctl_target": (40, 45), "tss_target": (350, 380)},
    {"phase": "Build 2",   "start": "2026-05-09", "end": "2026-05-22", "ctl_target": (45, 50), "tss_target": (380, 420)},
    {"phase": "Peak",      "start": "2026-05-23", "end": "2026-06-05", "ctl_target": (50, 52), "tss_target": (400, 450)},
    {"phase": "Taper 1",   "start": "2026-06-06", "end": "2026-06-12", "ctl_target": (50, 52), "tss_target": (200, 250)},
    {"phase": "Race Week", "start": "2026-06-13", "end": "2026-06-20", "ctl_target": (48, 50), "tss_target": (100, 150)},
]

PHASE_DESCRIPTIONS = {
    "Base 1":    "Aerobic volume and Z2 foundation. Bike priority. Build consistency.",
    "Base 2":    "Aerobic volume and Z2 foundation. Bike > Run > Swim. Swim resumes April.",
    "Late Base": "Extended aerobic base, swim fully integrated. Volume building.",
    "Build 1":   "Threshold and race-specific intensity. Brick sessions introduced. All three sports active.",
    "Build 2":   "Race-pace intervals, high intensity. Olympic distance simulation.",
    "Peak":      "Race-pace intervals, Olympic distance bricks, high intensity. Volume tapering begins.",
    "Taper 1":   "Volume reduction, race sharpening, leg freshness priority.",
    "Race Week": "Activation only. Rest and sharpen. No new fitness gains.",
}

# ─── DAY-TYPE RULES ──────────────────────────────────────────────────────────
# Reference for the weekly planner. Claude uses these descriptions when
# deciding what to assign each day.

DAY_TYPE_RULES = {
    "REST": {
        "description": "Complete rest, no training.",
        "max_hr": None,
        "duration_min": None,
    },
    "RECOVERY": {
        "description": "Z1/Z2 easy spin or short easy run, under 45 min, HR below 140.",
        "max_hr": 140,
        "duration_min": 45,
    },
    "Z2 ENDURANCE": {
        "description": "Aerobic base work, 60–90 min, strictly polarized, HR Z2.",
        "max_hr": BIKE_LTHR,
        "duration_min": 90,
    },
    "QUALITY": {
        "description": "Threshold or above. One named workout from the library.",
        "max_hr": None,
        "duration_min": None,
    },
    "LONG AEROBIC": {
        "description": "90–150 min Z2, bike or run, the week's long session.",
        "max_hr": BIKE_LTHR,
        "duration_min": 150,
    },
    "RACE-SPECIFIC": {
        "description": "Brick, transitions, or race-pace intervals. Final 6 weeks only.",
        "max_hr": None,
        "duration_min": None,
    },
}

# ─── HELPER: get current phase ───────────────────────────────────────────────

def get_current_phase():
    """Return the active periodization phase dict based on today's date."""
    today = date.today().isoformat()
    for phase in PERIODIZATION:
        if phase["start"] <= today <= phase["end"]:
            return phase
    if today < PERIODIZATION[0]["start"]:
        return PERIODIZATION[0]
    return PERIODIZATION[-1]


def weeks_to_race():
    """Return integer number of full weeks remaining until race day."""
    return max(0, (RACE_DATE - date.today()).days // 7)


def is_race_specific_window():
    """Return True if we are within 6 weeks of race day (RACE-SPECIFIC sessions allowed)."""
    return weeks_to_race() <= 6
