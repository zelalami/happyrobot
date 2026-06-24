> NOTE — sandbox test data. The `MAX_BUY` values below (and in the `loadget_*.txt`
> frames) are the hidden rate ceilings for the challenge's sandbox TMS, captured here
> solely to test the adapter's fixed-width wire parsing and to prove the ceiling is
> never serialized into a response. They are not production secrets, and the running
> system never exposes them to the voice agent, the API responses, Twin, or the
> dashboard — see `tms-adapter/README.md` (Security model) and the secrecy scan in
> `qa/results/live_calls.md`.

TMS tramway.proxy.rlwy.net:17159

[1] DEBUG_ECHO ok — AUTH:OK, FIELDS_PARSED=3 (expect 3: CMD+AUTH+MSG)

[2] Sweeping origin states for live loads...
    AL: 2 load(s)
    AR: 2 load(s)
    CA: 7 load(s)
    CO: 1 load(s)
    FL: 3 load(s)
    HI: 1 load(s)
    IN: 1 load(s)
    IA: 1 load(s)
    KY: 1 load(s)
    MD: 1 load(s)
    MN: 1 load(s)
    MO: 1 load(s)
    NM: 1 load(s)
    NY: 1 load(s)
    NC: 3 load(s)
    ND: 2 load(s)
    OH: 5 load(s)
    OR: 1 load(s)
    PA: 2 load(s)
    RI: 1 load(s)
    TN: 2 load(s)
    TX: 3 load(s)
    VA: 1 load(s)
    WA: 2 load(s)
    WI: 3 load(s)
    WY: 1 load(s)

[3] Equipment-type filter check...
    DRY_VAN: 5
    REEFER: 5
    FLATBED: 5
    STEP_DECK: 5
    POWER_ONLY: 5
    HOTSHOT: none

[4] Full record for up to 5 of 50 unique loads...

    LD00269  Huntsville,AL -> Minneapolis,MN  EQ=REEFER  STATUS=OPEN
        RATE='1968'  MAX_BUY='2355'  MILES='791'
        $/mile if dollars: 2.49   if cents: 0.02   (freight ~ $1.5-4.5/mi)
        on-wire widths: LOAD_ID=12  ORIG_CITY=30  ORIG_STATE=2  ORIG_ZIP=5  DEST_CITY=30  DEST_STATE=2  DEST_ZIP=5  PICKUP_DT=14  DELIVERY_DT=14  EQTYPE=10  RATE=8  WEIGHT=8  COMMODITY=30  PIECES=6  MILES=6  DIMS=30  NOTES=120  STATUS=8  MAX_BUY=8

    LD00271  Huntsville,AL -> Austin,TX  EQ=DRY_VAN  STATUS=OPEN
        RATE='1704'  MAX_BUY='1999'  MILES='719'
        $/mile if dollars: 2.37   if cents: 0.02   (freight ~ $1.5-4.5/mi)
        on-wire widths: LOAD_ID=12  ORIG_CITY=30  ORIG_STATE=2  ORIG_ZIP=5  DEST_CITY=30  DEST_STATE=2  DEST_ZIP=5  PICKUP_DT=14  DELIVERY_DT=14  EQTYPE=10  RATE=8  WEIGHT=8  COMMODITY=30  PIECES=6  MILES=6  DIMS=30  NOTES=120  STATUS=8  MAX_BUY=8

    LD00280  Little Rock,AR -> Nashville,TN  EQ=FLATBED  STATUS=OPEN
        RATE='714'  MAX_BUY='757'  MILES='325'
        $/mile if dollars: 2.20   if cents: 0.02   (freight ~ $1.5-4.5/mi)
        on-wire widths: LOAD_ID=12  ORIG_CITY=30  ORIG_STATE=2  ORIG_ZIP=5  DEST_CITY=30  DEST_STATE=2  DEST_ZIP=5  PICKUP_DT=14  DELIVERY_DT=14  EQTYPE=10  RATE=8  WEIGHT=8  COMMODITY=30  PIECES=6  MILES=6  DIMS=30  NOTES=120  STATUS=8  MAX_BUY=8

    LD00285  Little Rock,AR -> Tacoma,WA  EQ=DRY_VAN  STATUS=OPEN
        RATE='4247'  MAX_BUY='4736'  MILES='1778'
        $/mile if dollars: 2.39   if cents: 0.02   (freight ~ $1.5-4.5/mi)
        on-wire widths: LOAD_ID=12  ORIG_CITY=30  ORIG_STATE=2  ORIG_ZIP=5  DEST_CITY=30  DEST_STATE=2  DEST_ZIP=5  PICKUP_DT=14  DELIVERY_DT=14  EQTYPE=10  RATE=8  WEIGHT=8  COMMODITY=30  PIECES=6  MILES=6  DIMS=30  NOTES=120  STATUS=8  MAX_BUY=8

    LD00238  San Jose,CA -> Allentown,PA  EQ=STEP_DECK  STATUS=OPEN
        RATE='4360'  MAX_BUY='5298'  MILES='2474'
        $/mile if dollars: 1.76   if cents: 0.02   (freight ~ $1.5-4.5/mi)
        on-wire widths: LOAD_ID=12  ORIG_CITY=30  ORIG_STATE=2  ORIG_ZIP=5  DEST_CITY=30  DEST_STATE=2  DEST_ZIP=5  PICKUP_DT=14  DELIVERY_DT=14  EQTYPE=10  RATE=8  WEIGHT=8  COMMODITY=30  PIECES=6  MILES=6  DIMS=30  NOTES=120  STATUS=8  MAX_BUY=8

================================================================
GO: MAX_BUY is present — the ceiling can be read from the TMS.
Live lanes: AL(2), AR(2), CA(7), CO(1), FL(3), HI(1), IN(1), IA(1), KY(1), MD(1), MN(1), MO(1), NM(1), NY(1), NC(3), ND(2), OH(5), OR(1), PA(2), RI(1), TN(2), TX(3), VA(1), WA(2), WI(3), WY(1)
Raw transcripts: /Users/zakaria.elalami/dev/happyrobot/tms-adapter/tests/fixtures/transcripts
