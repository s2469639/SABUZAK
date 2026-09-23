import requests

payload = {
    "imposingCountries": [1,2,4,8,10,16,11,12,9,13,14,15,17,34,18,59,21,22,23,25,30,31,242,33,38,35,36,37,42,43,44,48,49,51,53,54,55,56,57,58,110,52,60,61,63,234,64,68,215,66,279,72,73,75,80,82,81,84,85,88,90,93,94,95,99,100,101,102,103,104,107,108,109,111,112,114,113,115,87,277,118,119,120,123,121,122,124,127,128,131,132,134,135,168,137,138,139,167,142,143,145,146,32,148,149,150,151,158,159,160,161,162,233,164,147,170,169,83,171,172,173,174,175,177,178,182,184,185,186,247,197,198,199,200,202,203,205,28,207,117,209,41,213,216,217,219,239,220,180,221,223,224,226,230,227,231,225,240,243,157,245,204,249,208,999],
    "allImposingCountries": True,
    "internationalStandardsImposing": False,
    "affectedCountries": [117, 999],
    "allAffectedCountries": False,
    "products": [2451798, 2451802, 2451803, 2451799, 2451800, 2451804, 2451805],
    "allProducts": False,
    "NTMType": None,
    "ExcludeHorizontalMeasures": None,
    "FromDate": None,
    "ToDate": None,
    "IsImportNtm": False,
    "IsUnilateral": None,
    "pageNumber": 1,
    "pageSize": 20,
    "columnsVisibility": {
        "countryImposingNTMsVisible": True, "affectedCountriesNamesVisible": True,
        "ntmCodeVisible": True, "ntmDescriptionVisible": True, "measureDescriptionVisible": True,
        "productDescriptionVisible": True, "hsCodeVisible": True, "issuingAgencyVisible": False,
        "regulationTitleVisible": True, "regulationSymbolVisible": False, "implementationDateVisible": True,
        "regulationFileVisible": True, "regulationOfficialTitleOriginalVisible": False,
        "measureDescriptionOriginalVisible": False, "measureProductDescriptionOriginalVisible": False,
        "supportingRegulationsVisible": False, "measureObjectivesOriginalVisible": False,
        "yearsOfDataCollectionVisible": False, "repealDateVisible": False, "objectiveCodesVisible": True,
    },
    "exportTo": "excel",
}

headers = {
    "Accept": "application/json, text/plain, */*",
    "Content-Type": "application/json",
    "Origin": "https://trainsonline.unctad.org",
    "Referer": "https://trainsonline.unctad.org/",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
}

r = requests.post("https://api-trains2.unctad.org/denormalisedMeasures", json=payload, headers=headers, timeout=30)
print("status:", r.status_code)
print("body:", r.text[:2000])