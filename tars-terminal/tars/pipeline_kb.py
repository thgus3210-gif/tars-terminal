"""Pipeline knowledge base: ticker -> [{a, tgt, mod, ind, ph}].

In production this is populated from AdisInsight (drug -> target, MoA/modality,
highest phase, indication, companies) via the company->ticker crosswalk, so
read-through covers the entire 160-name universe.

Until that adapter is wired, this seed carries the well-known large-cap
programs so the read-through engine and the modality/target tabs work for the
names most likely to move the class. Extend or replace wholesale from Adis.
"""

PIPELINE_KB = {
 "LLY": [{"a": "Tirzepatide", "tgt": "GLP-1/GIP", "mod": "Peptide", "ind": "Cardiometabolic", "ph": "Approved"},
         {"a": "Donanemab", "tgt": "Amyloid-β", "mod": "mAb", "ind": "Neuro", "ph": "Approved"},
         {"a": "Orforglipron", "tgt": "GLP-1", "mod": "Small molecule", "ind": "Cardiometabolic", "ph": "Phase 3"},
         {"a": "Lepodisiran", "tgt": "Lp(a)", "mod": "siRNA", "ind": "Cardiometabolic", "ph": "Phase 2"}],
 "NVO": [{"a": "Semaglutide", "tgt": "GLP-1", "mod": "Peptide", "ind": "Cardiometabolic", "ph": "Approved"},
         {"a": "CagriSema", "tgt": "GLP-1/Amylin", "mod": "Peptide", "ind": "Cardiometabolic", "ph": "Phase 3"}],
 "AMGN": [{"a": "MariTide", "tgt": "GLP-1/GIP", "mod": "Peptide", "ind": "Cardiometabolic", "ph": "Phase 2"},
          {"a": "Sotorasib", "tgt": "KRAS G12C", "mod": "Small molecule", "ind": "Oncology", "ph": "Approved"},
          {"a": "Olpasiran", "tgt": "Lp(a)", "mod": "siRNA", "ind": "Cardiometabolic", "ph": "Phase 3"}],
 "MRK": [{"a": "Pembrolizumab", "tgt": "PD-1", "mod": "mAb", "ind": "Oncology", "ph": "Approved"},
         {"a": "MK-0616", "tgt": "PCSK9", "mod": "Small molecule", "ind": "Cardiometabolic", "ph": "Phase 3"}],
 "NVS": [{"a": "Pelacarsen", "tgt": "Lp(a)", "mod": "ASO", "ind": "Cardiometabolic", "ph": "Phase 3"},
         {"a": "Pluvicto", "tgt": "PSMA", "mod": "Radioligand", "ind": "Oncology", "ph": "Approved"}],
 "ABBV": [{"a": "Risankizumab", "tgt": "IL-23", "mod": "mAb", "ind": "Immunology", "ph": "Approved"},
          {"a": "TL1A prog", "tgt": "TL1A", "mod": "mAb", "ind": "Immunology", "ph": "Phase 2"}],
 "JNJ": [{"a": "Milvexian", "tgt": "Factor XIa", "mod": "Small molecule", "ind": "Cardiometabolic", "ph": "Phase 3"},
         {"a": "Carvykti", "tgt": "BCMA", "mod": "Cell therapy", "ind": "Oncology", "ph": "Approved"},
         {"a": "Tremfya", "tgt": "IL-23", "mod": "mAb", "ind": "Immunology", "ph": "Approved"}],
 "BMY": [{"a": "Deucravacitinib", "tgt": "TYK2", "mod": "Small molecule", "ind": "Immunology", "ph": "Approved"},
         {"a": "Abecma", "tgt": "BCMA", "mod": "Cell therapy", "ind": "Oncology", "ph": "Approved"}],
 "PFE": [{"a": "Danuglipron", "tgt": "GLP-1", "mod": "Small molecule", "ind": "Cardiometabolic", "ph": "Phase 2"},
         {"a": "Elrexfio", "tgt": "BCMA", "mod": "Bispecific", "ind": "Oncology", "ph": "Approved"}],
 "VRTX": [{"a": "Trikafta", "tgt": "CFTR", "mod": "Small molecule", "ind": "Rare", "ph": "Approved"},
          {"a": "Casgevy", "tgt": "BCL11A", "mod": "Gene editing", "ind": "Rare", "ph": "Approved"}],
 "REGN": [{"a": "Dupixent", "tgt": "IL-4Rα", "mod": "mAb", "ind": "Immunology", "ph": "Approved"},
          {"a": "Linvoseltamab", "tgt": "BCMA", "mod": "Bispecific", "ind": "Oncology", "ph": "Phase 3"}],
 "BIIB": [{"a": "Leqembi", "tgt": "Amyloid-β", "mod": "mAb", "ind": "Neuro", "ph": "Approved"}],
 "ALNY": [{"a": "Vutrisiran", "tgt": "TTR", "mod": "siRNA", "ind": "Rare", "ph": "Approved"},
          {"a": "Zilebesiran", "tgt": "AGT", "mod": "siRNA", "ind": "Cardiometabolic", "ph": "Phase 2"}],
 "GILD": [{"a": "Trodelvy", "tgt": "Trop-2", "mod": "ADC", "ind": "Oncology", "ph": "Approved"}],
 "AZN": [{"a": "Enhertu", "tgt": "HER2", "mod": "ADC", "ind": "Oncology", "ph": "Approved"}],
 "ARGX": [{"a": "Vyvgart", "tgt": "FcRn", "mod": "mAb", "ind": "Immunology", "ph": "Approved"}],
 "SRPT": [{"a": "Elevidys", "tgt": "Dystrophin", "mod": "Gene therapy", "ind": "Rare", "ph": "Approved"}],
 "MRNA": [{"a": "mRNA-4157", "tgt": "Neoantigen", "mod": "mRNA", "ind": "Oncology", "ph": "Phase 3"}],
}
