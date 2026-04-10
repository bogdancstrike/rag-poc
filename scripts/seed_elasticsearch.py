"""Seed Elasticsearch with 10 themed intelligence indices, 10k docs each.

Themes:
  1. qsint_docs_ro_elections   — Romanian elections & political influence
  2. qsint_docs_cybersecurity  — Cyber threats, APTs, malware, vulnerabilities
  3. qsint_docs_financial_crime— Financial fraud, money laundering, crypto crime
  4. qsint_docs_disinformation — Global disinformation & narrative operations
  5. qsint_docs_geopolitics    — Geopolitical conflicts & state intelligence
  6. qsint_docs_narcotics      — Drug trafficking, darknet markets, cartels
  7. qsint_docs_terrorism      — Terrorism, extremism, radicalization
  8. qsint_docs_trafficking    — Human trafficking & smuggling networks
  9. qsint_docs_climate        — Climate & environmental disinformation
 10. qsint_docs_health         — Health disinformation & bio threats

Run:
  python3 scripts/seed_elasticsearch.py
  python3 scripts/seed_elasticsearch.py --count 10000 --batch 500
  python3 scripts/seed_elasticsearch.py --count 10000 --clear
  python3 scripts/seed_elasticsearch.py --count 10000 --indices ro_elections,cybersecurity
"""
import argparse
import random
import sys
import uuid
from datetime import timezone, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv
load_dotenv()

from faker import Faker
from elasticsearch.helpers import bulk

from src.datasource.es_client import ESClient

fake    = Faker(['en_US', 'en_GB', 'ro_RO', 'de_DE', 'fr_FR', 'ru_RU'])
fake_ro = Faker('ro_RO')
fake_en = Faker('en_US')

SENTIMENTS = ["hostile", "neutral", "supportive", "ambiguous", "inflammatory", "alarming", "cautionary"]


def _ts(days_back: int = 365) -> str:
    days = fake.random_int(min=0, max=days_back)
    return (fake_en.date_time_this_year(tzinfo=timezone.utc) - timedelta(days=days)).isoformat()


def _pick(*seq) -> str:
    return fake.random_element(seq)


def _para(n: int = 3) -> str:
    """Return n varied paragraphs of fake prose."""
    return "\n\n".join(fake_en.paragraph(nb_sentences=fake.random_int(min=3, max=6)) for _ in range(n))


def _long_text(max_chars: int = 800) -> str:
    return fake_en.text(max_nb_chars=max_chars)


# ══════════════════════════════════════════════════════════════════════════════
# 1. ROMANIAN ELECTIONS
# ══════════════════════════════════════════════════════════════════════════════

RO_PARTIES = [
    "PSD (Social Democratic Party)", "PNL (National Liberal Party)",
    "USR (Save Romania Union)", "AUR (Alliance for Romania's Unity)",
    "UDMR (Democratic Alliance of Hungarians)", "SOS România",
    "Forța Dreptei", "PRO România", "PMPND", "Reînnoim România",
]
RO_CANDIDATES = [
    "Călin Georgescu", "Elena Lasconi", "Marcel Ciolacu", "Nicolae Ciucă",
    "Mircea Geoană", "Victor Ponta", "Kelemen Hunor", "Diana Șoșoacă",
    "Cristian Terheș", "Silviu Predoiu",
]
RO_COUNTIES = [
    "Bucharest", "Cluj", "Iași", "Constanța", "Brașov", "Timișoara",
    "Galați", "Craiova", "Ploiești", "Sibiu", "Bacău", "Oradea",
    "Suceava", "Pitești", "Arad", "Focșani", "Buzău",
]
RO_ELECTION_TYPES = [
    "presidential election (Round 1)", "presidential election (Round 2)",
    "parliamentary election", "local elections", "European Parliament election",
    "referendum", "partial re-run election",
]
RO_TOPICS = [
    "foreign electoral interference", "TikTok algorithm manipulation",
    "vote-buying scheme", "exit poll suppression", "disinformation about candidate",
    "Facebook coordinated inauthentic behaviour", "astroturfing campaign",
    "deep-fake audio of politician", "fake polling data publication",
    "pro-Russian narrative amplification", "nationalist narrative injection",
    "postal vote fraud allegation", "electoral commission compromise attempt",
    "dark-money campaign financing", "anti-EU sentiment amplification",
    "bot network boosting candidate", "inflammatory religious narrative",
    "ethnic minority voter suppression", "diaspora manipulation campaign",
]
RO_PLATFORMS = ["Facebook", "TikTok", "Telegram", "YouTube", "WhatsApp", "Twitter/X", "OTV", "Antena 3", "Digi24"]
RO_ENTITIES = [
    "Russian GRU-linked operatives", "Wagner Group affiliates", "FSB Unit 72949",
    "Internet Research Agency Romania desk", "domestic far-right network",
    "anonymous Telegram channel cluster", "offshore PAC via Cyprus shell companies",
    "coordinated bot farm (origin: Moldova)", "pro-Kremlin influencer network",
    "Romanian diasporic extremist group",
]
RO_INDICATORS = [
    "spike in Telegram channel memberships 48 h before election day",
    "identical message templates forwarded across 400+ WhatsApp groups",
    "TikTok hashtag volume increased 1,200% in 72 hours",
    "Facebook ad spend traced to offshore shell accounts",
    "coordinated mass-reporting of opposition candidate pages",
    "AI-generated profile photos on newly created accounts",
    "VPN exit nodes in Moscow correlated with bot account logins",
    "inauthentic amplification of exit-poll manipulation narrative",
    "deep-fake audio clip circulated hours before polls closed",
    "coordinated 1-star reviews of electoral authority mobile app",
]


def generate_ro_elections_doc(idx: int) -> dict:
    topic      = _pick(*RO_TOPICS)
    entity     = _pick(*RO_ENTITIES)
    platform   = _pick(*RO_PLATFORMS)
    county     = _pick(*RO_COUNTIES)
    candidate  = _pick(*RO_CANDIDATES)
    party      = _pick(*RO_PARTIES)
    el_type    = _pick(*RO_ELECTION_TYPES)
    sentiment  = _pick(*SENTIMENTS)
    indicator  = _pick(*RO_INDICATORS)
    indicator2 = _pick(*RO_INDICATORS)
    confidence = fake.random_int(min=40, max=97)
    poll_margin = round(random.uniform(-8.5, 12.3), 2)
    amount_eur = fake.random_int(min=5000, max=2_000_000)
    template   = fake.random_int(min=1, max=5)

    title = f"[RO-ELEC-{idx:06d}] {topic.title()} — {county} / {el_type}"

    if template == 1:
        body = (
            f"Report ID: RO-ELEC-{idx:06d}\n"
            f"Classification: CONFIDENTIAL\n"
            f"Analyst: {fake.name()}\n"
            f"Election: {el_type}\n\n"
            f"SUMMARY\n"
            f"A {sentiment} {topic} has been detected targeting voters in {county} ahead of the {el_type}. "
            f"The operation is attributed with {confidence}% confidence to {entity}. "
            f"Primary platform of dissemination: {platform}.\n\n"
            f"OPERATIONAL DETAIL\n"
            f"Candidate {candidate} ({party}) is the apparent beneficiary or target of this operation. "
            f"Current polling margin in the affected area stands at {poll_margin:+.1f}%. "
            f"Indicators observed include: {indicator}; additionally, {indicator2} was confirmed by SIGINT collection.\n\n"
            f"NARRATIVE THEMES\n"
            f"{_para(2)} "
            f"Key messages promote anti-{_pick('EU', 'NATO', 'IMF', 'Soros', 'Western')} sentiment and "
            f"question the legitimacy of {_pick('electoral commission', 'vote counting', 'diaspora ballots', 'postal voting')}.\n\n"
            f"ATTRIBUTION ASSESSMENT\n"
            f"OSINT analysis links infrastructure to {entity}. {_para(1)} "
            f"Historical pattern overlap with {_pick('2016 US election op', '2022 French election op', 'Brexit campaign', '2023 Slovak election op')} assessed as HIGH.\n\n"
            f"RECOMMENDED ACTIONS\n"
            f"Alert BEC (Bureau Electoral Central) and SRI. "
            f"Request {platform} takedown of coordinated inauthentic accounts. "
            f"Monitor {county} district for escalation. "
            f"Cross-reference with EU DisinfoLab database entries.\n"
        )
    elif template == 2:
        body = (
            f"INTELLIGENCE BULLETIN — ELECTORAL INTEGRITY\n\n"
            f"File: RO-ELEC-{idx:06d}  Sensitivity: {_pick('RESTRICTED', 'CONFIDENTIAL', 'SECRET')}\n"
            f"Issued: {_ts(30)}\n\n"
            f"Reporting on active {topic} in the context of the upcoming {el_type}. "
            f"Observed on {platform} and corroborated via human source in {county}. "
            f"Target candidate: {candidate}. Sponsoring entity assessed as {entity}.\n\n"
            f"KEY FINDINGS\n"
            f"1. {indicator.capitalize()}.\n"
            f"2. {indicator2.capitalize()}.\n"
            f"3. Financial flows of approximately €{amount_eur:,} traced through "
            f"{_pick('Cyprus', 'Malta', 'UAE', 'Liechtenstein')} shell accounts to domestic campaign affiliates.\n\n"
            f"DISINFORMATION CONTENT\n"
            f"{_para(2)}\n\n"
            f"RISK LEVEL\n"
            f"{'HIGH' if confidence > 75 else 'MEDIUM'} — potential impact on "
            f"{_pick('turnout', 'candidate perception', 'institutional trust', 'diaspora vote')} assessed as significant.\n"
        )
    elif template == 3:
        body = (
            f"Electoral Monitoring Report | {el_type.upper()}\n"
            f"Reference: RO-ELEC-{idx:06d}\n\n"
            f"Subject: {topic.title()}\n"
            f"Location: {county}, Romania\n"
            f"Platform: {platform}\n\n"
            f"Threat actor {entity} has launched a {sentiment} {topic} in {county}. "
            f"The campaign is timed to coincide with the final week before {el_type} polling.\n\n"
            f"{_long_text(600)}\n\n"
            f"Party {party} and its candidate {candidate} are mentioned in "
            f"{fake.random_int(min=60, max=98)}% of the flagged content. "
            f"Sentiment analysis of {fake.random_int(min=500, max=50000):,} posts: "
            f"{fake.random_int(min=30, max=75)}% negative framing, "
            f"{fake.random_int(min=5, max=30)}% calls to action.\n\n"
            f"Technical note: {indicator}. Confidence {confidence}%.\n"
            f"{_para(1)}\n"
        )
    elif template == 4:
        # News-article style
        body = (
            f"ELECTORAL SECURITY BRIEFING — {county.upper()}\n"
            f"Date: {_ts(30)} | Ref: RO-ELEC-{idx:06d}\n\n"
            f"Analysts have identified a coordinated {topic} campaign centred on the {county} electorate "
            f"ahead of the {el_type}. The operation, attributed to {entity}, exploits {platform} to disseminate "
            f"content supporting {candidate} ({party}) while undermining electoral institutions.\n\n"
            f"Observed technical indicators confirm the campaign's inorganic character. {indicator.capitalize()}. "
            f"{indicator2.capitalize()}. Infrastructure analysis indicates "
            f"{_pick('offshore hosting', 'anonymised routing', 'cross-border server clusters', 'bulletproof hosting')} "
            f"consistent with previous {_pick('Russian', 'Chinese', 'Iranian', 'domestic')} influence operations.\n\n"
            f"{_long_text(700)}\n\n"
            f"Financial linkages: approximately €{amount_eur:,} in campaign-adjacent spending traced to "
            f"{_pick('Cyprus', 'Malta', 'UAE')} through multiple shell layers. "
            f"Polling margin in affected district: {poll_margin:+.1f}%. Confidence: {confidence}%.\n"
        )
    else:
        # Raw field notes style
        body = (
            f"[FIELD NOTES — SIGINT/OSINT FUSION]\n"
            f"Ref: RO-ELEC-{idx:06d} | Analyst: {fake.name()} | Date: {_ts(10)}\n\n"
            f"Platform: {platform}\n"
            f"Affected area: {county}\n"
            f"Election cycle: {el_type}\n\n"
            f"Observations:\n"
            f"— {indicator}\n"
            f"— {indicator2}\n"
            f"— Candidate {candidate} ({party}) content amplified {fake.random_int(min=300, max=5000)}% above baseline\n"
            f"— Cross-platform coordination confirmed between {platform} and {_pick('Telegram', 'WhatsApp', 'VK')}\n\n"
            f"Attribution note: {entity} infrastructure fingerprint matches previous ops. "
            f"Confidence {confidence}%.\n\n"
            f"Context:\n"
            f"{_long_text(500)}\n\n"
            f"Escalation risk: {'HIGH' if confidence > 70 else 'MEDIUM'}. "
            f"Polling margin delta: {poll_margin:+.1f}%. Further monitoring recommended.\n"
        )

    return {
        "title": title, "text": body, "topic": topic, "entity": entity,
        "platform": platform, "region": county, "sentiment": sentiment,
        "candidate": candidate, "party": party, "election_type": el_type,
        "poll_margin": poll_margin, "confidence": confidence,
        "analyst": fake.name(), "source": "electoral-intelligence",
        "created_at": _ts(180), "tags": fake.random_elements(RO_TOPICS, length=3, unique=True),
    }


# ══════════════════════════════════════════════════════════════════════════════
# 2. CYBERSECURITY
# ══════════════════════════════════════════════════════════════════════════════

CYBER_GROUPS = [
    "APT28 (Fancy Bear)", "APT29 (Cozy Bear)", "APT41 (Double Dragon)",
    "Lazarus Group", "Sandworm", "Charming Kitten", "LockBit 3.0",
    "BlackCat/ALPHV", "Cl0p", "Conti successors", "DarkSide remnants",
    "Scattered Spider", "UNC4393", "Volt Typhoon", "Salt Typhoon",
    "RomCom RAT operators", "Gamaredon", "Turla", "OilRig (APT34)",
    "Kimsuky", "FIN7", "TA505", "Muddled Libra",
]
MALWARE = [
    "LockBit 3.0 ransomware", "BlackCat ransomware", "Cobalt Strike beacon",
    "Emotet loader", "QakBot", "IcedID", "Bumblebee loader",
    "SystemBC proxy", "Brute Ratel C4", "Sliver C2 framework",
    "AsyncRAT", "NjRAT", "DarkComet", "RedLine Stealer",
    "Raccoon Stealer v2", "Vidar infostealer", "MetaStealer",
    "PlugX", "ShadowPad", "Gh0stRAT", "Havoc C2",
]
ATTACK_VECTORS = [
    "spearphishing with malicious ISO attachment",
    "zero-day in Microsoft Exchange",
    "SQL injection via unpatched web application",
    "supply chain compromise of managed-service provider",
    "RDP brute-force against exposed endpoint",
    "malicious macro-enabled Office document",
    "watering hole on industry sector website",
    "drive-by download via compromised ad network",
    "credential stuffing using leaked password dump",
    "social engineering of IT helpdesk",
    "VPN appliance exploitation",
    "Citrix Bleed exploitation (CVE-2023-4966)",
    "MOVEit Transfer SQL injection (CVE-2023-34362)",
    "TeamCity authentication bypass (CVE-2024-27198)",
]
CYBER_SECTORS = [
    "critical national infrastructure", "healthcare & hospitals",
    "financial services", "government & defence", "energy & utilities",
    "telecommunications", "education & universities", "manufacturing",
    "legal & professional services", "retail & e-commerce", "media",
]
CYBER_REGIONS = [
    "Western Europe", "Eastern Europe", "North America", "Asia-Pacific",
    "Middle East", "Global", "NATO member states", "EU institutions",
]
MITRE_TACTICS = [
    "Initial Access (T1566)", "Execution (T1059)", "Persistence (T1547)",
    "Privilege Escalation (T1068)", "Defence Evasion (T1036)",
    "Credential Access (T1003)", "Discovery (T1082)",
    "Lateral Movement (T1021)", "Collection (T1005)",
    "Exfiltration (T1041)", "Impact (T1486)",
]
CVES = [
    "CVE-2024-27198", "CVE-2024-3400", "CVE-2023-4966", "CVE-2023-34362",
    "CVE-2023-44487", "CVE-2024-21762", "CVE-2024-1709", "CVE-2023-46805",
    "CVE-2024-21887", "CVE-2024-6387",
]


def generate_cybersecurity_doc(idx: int) -> dict:
    group      = _pick(*CYBER_GROUPS)
    malware    = _pick(*MALWARE)
    vector     = _pick(*ATTACK_VECTORS)
    sector     = _pick(*CYBER_SECTORS)
    region     = _pick(*CYBER_REGIONS)
    tactic     = _pick(*MITRE_TACTICS)
    tactic2    = _pick(*MITRE_TACTICS)
    cve        = _pick(*CVES)
    confidence = fake.random_int(min=50, max=98)
    ransom_usd = fake.random_int(min=50_000, max=15_000_000)
    dwell_days = fake.random_int(min=1, max=180)
    data_gb    = round(random.uniform(0.5, 4000), 1)
    severity   = _pick("CRITICAL", "HIGH", "MEDIUM")
    sentiment  = _pick(*SENTIMENTS)
    victims    = fake.random_int(min=1, max=300)
    template   = fake.random_int(min=1, max=5)

    title = f"[CYBER-{idx:06d}] {group} targets {sector} — {vector[:40]}"

    if template == 1:
        body = (
            f"TLP:AMBER | CYBER-{idx:06d}\n"
            f"Severity: {severity}\n"
            f"Sector: {sector.title()}\n\n"
            f"THREAT SUMMARY\n"
            f"{group} has been observed conducting a campaign against {sector} organisations in {region}. "
            f"Initial access achieved via {vector}. Primary payload: {malware}.\n\n"
            f"TECHNICAL ANALYSIS\n"
            f"CVE exploited: {cve}\n"
            f"Dwell time: {dwell_days} days\n"
            f"Data exfiltrated: ~{data_gb} GB\n"
            f"MITRE ATT&CK: {tactic}, {tactic2}\n\n"
            f"{_para(2)}\n\n"
            f"INDICATORS OF COMPROMISE\n"
            f"C2 IP: {fake_en.ipv4_public()}\n"
            f"C2 IP: {fake_en.ipv4_public()}\n"
            f"Domain: {fake_en.domain_name()}\n"
            f"SHA-256: {fake_en.sha256()}\n"
            f"SHA-256: {fake_en.sha256()}\n\n"
            f"IMPACT ASSESSMENT\n"
            f"Ransom demand: ${ransom_usd:,}. {_para(1)}\n\n"
            f"RECOMMENDATIONS\n"
            f"Patch {cve} immediately. Hunt for {malware} artefacts. "
            f"Rotate credentials for {_pick('admin', 'domain admin', 'service')} accounts. "
            f"Engage IR team within 24 h if indicators found.\n"
        )
    elif template == 2:
        body = (
            f"Threat Intelligence Report: {group}\n\n"
            f"Classification: RESTRICTED | TLP:AMBER\n"
            f"Reference: CYBER-{idx:06d}\n"
            f"Confidence: {confidence}%\n\n"
            f"{group} is actively targeting {sector} entities across {region} "
            f"as part of an ongoing campaign. "
            f"The group leverages {malware} following initial access via {vector}.\n\n"
            f"Campaign Timeline:\n"
            f"First observed: {_ts(90)}\n"
            f"Last activity: {_ts(7)}\n"
            f"Total victims identified: {victims}\n\n"
            f"MITRE ATT&CK Coverage:\n"
            f"- {tactic}\n"
            f"- {tactic2}\n"
            f"- {_pick(*MITRE_TACTICS)}\n\n"
            f"Intelligence Value:\n"
            f"{_long_text(600)}\n\n"
            f"Remediation Priority: {severity}\n"
            f"{_para(1)}\n"
        )
    elif template == 3:
        body = (
            f"SIGINT/CYBINT FUSION REPORT — {severity}\n"
            f"ID: CYBER-{idx:06d}\n\n"
            f"Threat actor: {group}\n"
            f"Target sector: {sector}\n"
            f"Region: {region}\n\n"
            f"Observed attack chain: {vector} → {malware} deployment → {tactic} → data exfiltration.\n\n"
            f"The adversary exploited {cve} to gain initial foothold in "
            f"{_pick('VPN appliance', 'edge device', 'web server', 'email gateway')}. "
            f"Lateral movement occurred over {dwell_days} days before detection. "
            f"Estimated data loss: {data_gb} GB including "
            f"{_pick('PII', 'intellectual property', 'financial records', 'classified documents', 'source code')}.\n\n"
            f"{_long_text(700)}\n\n"
            f"Network IOCs:\n"
            f"  {fake_en.ipv4_public()} (C2 beacon)\n"
            f"  {fake_en.ipv4_public()} (exfil endpoint)\n"
            f"  {fake_en.domain_name()} (dropper domain)\n\n"
            f"Ransom demand: ${ransom_usd:,} in {_pick('Bitcoin', 'Monero', 'Ethereum')}. "
            f"Attribution confidence: {confidence}%.\n"
        )
    elif template == 4:
        # Incident response log style
        body = (
            f"INCIDENT RESPONSE LOG — {sector.upper()}\n"
            f"Case: CYBER-{idx:06d}  |  Severity: {severity}\n"
            f"Lead analyst: {fake_en.name()}  |  Opened: {_ts(14)}\n\n"
            f"INCIDENT TIMELINE\n"
            f"T+00:00  {vector.capitalize()} detected by endpoint sensor\n"
            f"T+{fake.random_int(min=1,max=8):02d}:{fake.random_int(min=0,max=59):02d}  {malware} payload dropped on host {fake_en.ipv4_private()}\n"
            f"T+{fake.random_int(min=8,max=24):02d}:00  Lateral movement to domain controller via {tactic}\n"
            f"T+{dwell_days}d  Data staging and exfiltration of {data_gb} GB confirmed\n"
            f"T+{dwell_days+fake.random_int(min=1,max=7)}d  Ransom note deployed — demand ${ransom_usd:,}\n\n"
            f"THREAT ACTOR PROFILE\n"
            f"{group} — {_pick('Nation-state', 'Criminal', 'Hacktivist', 'Hybrid')} actor. "
            f"Known TTPs include {tactic} and {tactic2}. "
            f"Exploited vulnerability: {cve}.\n\n"
            f"{_long_text(600)}\n\n"
            f"NETWORK FORENSICS\n"
            f"Primary C2: {fake_en.ipv4_public()} ({fake_en.domain_name()})\n"
            f"Secondary C2: {fake_en.ipv4_public()}\n"
            f"Exfil endpoint: {fake_en.ipv4_public()}\n"
            f"Malware hash: {fake_en.sha256()}\n\n"
            f"STATUS: {_pick('Contained', 'Active', 'Post-incident review', 'Remediation in progress')}\n"
        )
    else:
        # Threat advisory style
        body = (
            f"THREAT ADVISORY — {severity} SEVERITY\n"
            f"Advisory ID: CYBER-{idx:06d}\n"
            f"Affected sector: {sector}\n"
            f"Geographic scope: {region}\n\n"
            f"This advisory concerns active exploitation by {group} using {malware} "
            f"to target {sector} organisations. The initial intrusion vector is {vector}.\n\n"
            f"{_long_text(500)}\n\n"
            f"TECHNICAL DETAILS\n"
            f"Vulnerability: {cve}\n"
            f"Post-exploitation: {tactic}, {tactic2}\n"
            f"Persistence mechanism: {_pick('scheduled task', 'registry run key', 'WMI subscription', 'service installation', 'boot sector modification')}\n"
            f"Exfiltration channel: {_pick('HTTPS to C2', 'DNS tunnelling', 'cloud storage abuse', 'ICMP covert channel')}\n\n"
            f"AFFECTED VERSIONS\n"
            f"{_para(1)}\n\n"
            f"MITIGATION STEPS\n"
            f"1. Apply patch for {cve} across all vulnerable assets immediately.\n"
            f"2. Enable enhanced logging for {_pick('PowerShell', 'WMI', 'LDAP', 'SMB')} activity.\n"
            f"3. Block listed IOCs at perimeter.\n"
            f"4. Conduct threat hunt using provided Sigma/YARA rules.\n\n"
            f"Confidence: {confidence}%  |  Victims confirmed: {victims}\n"
        )

    return {
        "title": title, "text": body, "topic": f"{group} campaign",
        "entity": group, "platform": "darknet / email / RDP",
        "region": region, "sentiment": sentiment,
        "malware_family": malware, "attack_vector": vector,
        "affected_sector": sector, "severity": severity, "cve": cve,
        "dwell_days": dwell_days, "data_exfil_gb": data_gb,
        "confidence": confidence, "ransom_usd": ransom_usd,
        "analyst": fake_en.name(), "source": "cyber-threat-intelligence",
        "created_at": _ts(365), "tags": fake.random_elements(MITRE_TACTICS, length=3, unique=True),
    }


# ══════════════════════════════════════════════════════════════════════════════
# 3. FINANCIAL CRIME
# ══════════════════════════════════════════════════════════════════════════════

FIN_SCHEMES = [
    "money laundering via shell company cascade", "cryptocurrency tumbler operation",
    "trade-based money laundering (TBML)", "real-estate value manipulation",
    "hawala network", "SWIFT fraud", "romance/investment scam (pig-butchering)",
    "BEC (Business Email Compromise) campaign", "darknet drug proceeds laundering",
    "NFT wash-trading scheme", "pump-and-dump crypto scheme",
    "synthetic identity fraud", "account takeover operation",
    "tax evasion via offshore trust", "mortgage fraud network",
    "invoice fraud against EU institutions", "crypto bridge exploit",
]
FIN_GROUPS = [
    "Lazarus Group (DPRK financial ops)", "FIN7", "Carbanak successors",
    "TA558 / wire fraud syndicate", "West African cybercrime network",
    "Eastern European money-mule network", "Chinese crypto laundering operation",
    "Russian oligarch asset-concealment network", "Colombian cartel financial cell",
    "Anonymous darknet laundering service",
]
FIN_CRYPTOS = [
    "Bitcoin (BTC)", "Monero (XMR)", "Ethereum (ETH)",
    "USDT (Tether)", "Litecoin (LTC)", "Zcash (ZEC)",
]
FIN_JURISDICTIONS = [
    "British Virgin Islands", "Cayman Islands", "Malta", "Cyprus",
    "Seychelles", "Panama", "Liechtenstein", "UAE (Dubai)",
    "Singapore", "Marshall Islands", "Vanuatu", "Belize",
]
FIN_SECTORS = ["banking", "real estate", "luxury goods", "cryptocurrency exchange", "fintech", "insurance", "gambling"]


def generate_financial_crime_doc(idx: int) -> dict:
    scheme     = _pick(*FIN_SCHEMES)
    group      = _pick(*FIN_GROUPS)
    crypto     = _pick(*FIN_CRYPTOS)
    juris      = _pick(*FIN_JURISDICTIONS)
    juris2     = _pick(*FIN_JURISDICTIONS)
    sector     = _pick(*FIN_SECTORS)
    amount     = fake.random_int(min=100_000, max=800_000_000)
    accounts   = fake.random_int(min=5, max=2000)
    confidence = fake.random_int(min=45, max=96)
    sentiment  = _pick(*SENTIMENTS)
    template   = fake.random_int(min=1, max=5)

    title = f"[FINCRIME-{idx:06d}] {scheme.title()} — {group}"

    if template == 1:
        body = (
            f"Case: FINCRIME-{idx:06d}\n"
            f"Classification: RESTRICTED\n"
            f"Analyst: {fake_en.name()}\n\n"
            f"EXECUTIVE SUMMARY\n"
            f"A {scheme} has been identified, orchestrated by {group}. "
            f"Funds totalling approximately €{amount:,} implicated across {accounts} accounts. "
            f"Primary layering jurisdiction: {juris}. Vehicle: {crypto}.\n\n"
            f"FINANCIAL FLOW ANALYSIS\n"
            f"{_long_text(600)}\n"
            f"The {sector} sector was used as the primary integration channel. "
            f"Shell companies in {juris} and {juris2} were identified as key nodes.\n\n"
            f"BLOCKCHAIN FORENSICS\n"
            f"Wallet cluster: {fake_en.sha256()[:34]}\n"
            f"Associated exchange: {_pick('Binance', 'KuCoin', 'Huobi', 'OKX', 'unregulated P2P exchange')}\n"
            f"Mixing service: {_pick('Tornado Cash', 'ChipMixer', 'Wasabi Wallet', 'YoMix', 'custom tumbler')}\n\n"
            f"ATTRIBUTION\n"
            f"Attributed to {group} with {confidence}% confidence based on TTP overlap and financial intelligence.\n"
            f"{_para(1)}\n"
        )
    elif template == 2:
        body = (
            f"FINANCIAL INTELLIGENCE UNIT — CASE BRIEF\n"
            f"Reference: FINCRIME-{idx:06d}\n\n"
            f"Scheme type: {scheme}\n"
            f"Suspected orchestrator: {group}\n"
            f"Estimated proceeds: €{amount:,}\n"
            f"Layering jurisdictions: {juris}, {juris2}\n\n"
            f"{_long_text(700)}\n\n"
            f"The operation exploited weak AML controls in {sector} entities. "
            f"{accounts} mule accounts used for placement. "
            f"Layering achieved through "
            f"{_pick('real estate purchases', 'luxury car fleet', 'crypto conversion', 'trade invoice manipulation', 'casino chips')} "
            f"before integration into legitimate {sector} businesses.\n\n"
            f"Crypto footprint: {crypto} with estimated "
            f"{_pick('low', 'medium', 'high')} obfuscation complexity.\n"
            f"Confidence: {confidence}%\n"
        )
    elif template == 3:
        body = (
            f"THREAT INTELLIGENCE — FINANCIAL CRIME\n\n"
            f"ID: FINCRIME-{idx:06d}\n"
            f"Type: {scheme}\n\n"
            f"{_para(2)}\n\n"
            f"Actor: {group}\n"
            f"Scale: €{amount:,} across {accounts} flagged accounts\n"
            f"Mechanism: {crypto} → {_pick('P2P exchange', 'OTC desk', 'unregulated exchange', 'DEX')} → {sector} integration\n\n"
            f"Layering jurisdictions:\n"
            f"- {juris}\n"
            f"- {juris2}\n"
            f"- {_pick(*FIN_JURISDICTIONS)}\n\n"
            f"Intelligence assessment: {_long_text(400)}\n\n"
            f"Confidence in attribution: {confidence}%. "
            f"Linked to {_pick('FATF grey-list country', 'UN-sanctioned entity', 'OFAC SDN list entry', 'Europol most-wanted network')}.\n"
        )
    elif template == 4:
        # Crypto investigation deep-dive
        body = (
            f"CRYPTOCURRENCY INVESTIGATION REPORT\n"
            f"Case: FINCRIME-{idx:06d}  |  Lead: {fake_en.name()}\n\n"
            f"Overview: {scheme} attributed to {group}.\n\n"
            f"TRANSACTION GRAPH SUMMARY\n"
            f"Origin wallet: {fake_en.sha256()[:42]}\n"
            f"Total flow: {crypto} equivalent of €{amount:,}\n"
            f"Hop count before cash-out: {fake.random_int(min=3, max=20)}\n"
            f"Exchanges used: {_pick('Binance', 'Kraken', 'Coinbase')}, {_pick('KuCoin', 'OKX', 'Huobi')}\n"
            f"Mixing detected: Yes — {_pick('Tornado Cash protocol', 'Wasabi CoinJoin', 'ChipMixer shards', 'custom smart contract')}\n\n"
            f"LAYERING ANALYSIS\n"
            f"{_long_text(600)}\n\n"
            f"The proceeds were moved through {juris} and {juris2} shell structures before "
            f"re-entering the legitimate {sector} economy. AML controls at receiving institutions "
            f"rated as {_pick('inadequate', 'partially effective', 'bypassed via insider')}.\n\n"
            f"ASSET RECOVERY POTENTIAL\n"
            f"Estimated recoverable: €{int(amount * random.uniform(0.05, 0.4)):,} ({fake.random_int(min=5, max=40)}% of total).\n"
            f"Freeze orders recommended for: {juris}, {juris2}.\n"
        )
    else:
        # Regulatory memo style
        body = (
            f"REGULATORY INTELLIGENCE MEMO\n"
            f"To: Financial Intelligence Unit\n"
            f"From: Analytical Cell\n"
            f"Subject: {scheme.title()} — {group}\n"
            f"Ref: FINCRIME-{idx:06d}\n\n"
            f"This memo summarises intelligence on a {scheme} linked to {group}. "
            f"The scheme involves approximately €{amount:,} across {accounts} identified accounts "
            f"in the {sector} sector, with primary layering in {juris}.\n\n"
            f"{_long_text(800)}\n\n"
            f"Key risk factors: {_pick('cross-border complexity', 'crypto obfuscation', 'use of legal professionals', 'nominee directors', 'bearer instruments')}. "
            f"Jurisdictional cooperation with {juris} and {juris2} essential to asset recovery. "
            f"Confidence: {confidence}%.\n"
        )

    return {
        "title": title, "text": body, "topic": scheme,
        "entity": group, "platform": "darknet / banking / crypto",
        "region": juris, "sentiment": sentiment,
        "scheme_type": scheme, "amount_eur": amount, "crypto_currency": crypto,
        "jurisdiction": juris, "account_count": accounts, "confidence": confidence,
        "analyst": fake_en.name(), "source": "financial-crime-intelligence",
        "created_at": _ts(365), "tags": fake.random_elements(FIN_SCHEMES, length=3, unique=True),
    }


# ══════════════════════════════════════════════════════════════════════════════
# 4. DISINFORMATION
# ══════════════════════════════════════════════════════════════════════════════

DISINFO_NARRATIVES = [
    "NATO preparing false-flag attack on European soil",
    "EU leaders secretly plan to abolish national sovereignty",
    "COVID vaccines contain microchip tracking technology",
    "Western-funded NGOs are destabilising sovereign governments",
    "US bioweapon labs operating in Ukraine confirmed",
    "Climate change is a hoax manufactured by the WEF",
    "George Soros controls Western election outcomes",
    "UN migration pact is a replacement strategy",
    "5G towers used for mass surveillance and mind control",
    "Zelensky hiding billions in offshore accounts",
    "AI-generated fake atrocity footage attributed to Russia",
    "EU imposing digital ID for total population control",
    "Deep-state network exposed in government",
    "Israel/Hamas conflict framing to incite European violence",
    "BRICS currency will collapse the dollar within months",
]
DISINFO_CONTENT_TYPES = [
    "deep-fake video", "AI-generated article", "fabricated screenshot",
    "out-of-context imagery", "false attribution quote",
    "synthetic audio recording", "manipulated statistical graph",
    "coordinated hashtag trend", "astroturfed petition",
    "fake expert testimony", "impersonation of official source",
]
DISINFO_ENTITIES = [
    "Kremlin strategic communications directorate", "Chinese MFA 50-cent army",
    "Iranian IRGC influence unit", "Venezuelan SEBIN media ops",
    "domestic populist media outlet network", "anonymous Telegram mega-channel cluster",
    "AI content farm (origin unknown)", "far-right European network",
    "state-affiliated YouTube channel network", "pseudo-academic front organisation",
]
DISINFO_PLATFORMS = ["Telegram", "Twitter/X", "Facebook", "TikTok", "YouTube", "Reddit", "Rumble", "BitChute", "VK"]
DISINFO_REGIONS = ["Global", "Western Europe", "Eastern Europe", "Latin America", "Sub-Saharan Africa", "Middle East"]


def generate_disinformation_doc(idx: int) -> dict:
    narrative   = _pick(*DISINFO_NARRATIVES)
    ctype       = _pick(*DISINFO_CONTENT_TYPES)
    entity      = _pick(*DISINFO_ENTITIES)
    platform    = _pick(*DISINFO_PLATFORMS)
    region      = _pick(*DISINFO_REGIONS)
    reach       = fake.random_int(min=1000, max=50_000_000)
    engagements = fake.random_int(min=500, max=5_000_000)
    confidence  = fake.random_int(min=45, max=97)
    sentiment   = _pick(*SENTIMENTS)
    template    = fake.random_int(min=1, max=5)

    title = f"[DISINFO-{idx:06d}] Narrative: «{narrative[:60]}» — {platform}"

    if template == 1:
        body = (
            f"DISINFO-{idx:06d} | TLP:WHITE\n"
            f"Narrative detected: {narrative}\n"
            f"Platform: {platform}\n"
            f"Content type: {ctype}\n\n"
            f"SITUATION REPORT\n"
            f"A {sentiment} {ctype} promoting the narrative «{narrative}» has been detected on {platform}. "
            f"The content originated from {entity} and achieved an estimated reach of {reach:,} users "
            f"with {engagements:,} engagements in {region}.\n\n"
            f"CONTENT ANALYSIS\n"
            f"{_long_text(600)}\n\n"
            f"AMPLIFICATION NETWORK\n"
            f"The narrative was seeded through {fake.random_int(min=5, max=500)} accounts before organic amplification. "
            f"{_para(1)}\n\n"
            f"ATTRIBUTION\n"
            f"Attributed to {entity} with {confidence}% confidence. "
            f"Infrastructure overlap with previously documented operations identified.\n\n"
            f"DEBUNKING STATUS\n"
            f"{_pick('Fully debunked', 'Partially debunked', 'Contested', 'Under review')} by "
            f"{_pick('EU DisinfoLab', 'Bellingcat', 'DFRLab', 'Snopes', 'FactCheck.org', 'StopFake')}. "
            f"Viral coefficient: {round(random.uniform(1.1, 8.5), 2)}.\n"
        )
    elif template == 2:
        body = (
            f"NARRATIVE THREAT ASSESSMENT\n\n"
            f"Ref: DISINFO-{idx:06d}\n"
            f"Source actor: {entity}\n"
            f"Target audience: {region}\n\n"
            f"The false narrative — «{narrative}» — is spreading across {platform} via {ctype}. "
            f"{_long_text(500)}\n\n"
            f"Spread metrics:\n"
            f"- Estimated reach: {reach:,} accounts\n"
            f"- Engagements: {engagements:,}\n"
            f"- Cross-platform spread: {_pick('Yes', 'No', 'Partial')}\n"
            f"- Trending in: {_pick('Germany', 'France', 'Poland', 'Romania', 'US', 'Brazil', 'India')}\n\n"
            f"Linguistic markers: {_para(1)}\n\n"
            f"Assessment: {_para(1)}\n"
        )
    elif template == 3:
        body = (
            f"OSINT MONITORING ALERT — {platform.upper()}\n"
            f"Case: DISINFO-{idx:06d} | Priority: {_pick('HIGH', 'MEDIUM', 'LOW')}\n\n"
            f"Detected {ctype} spreading narrative: «{narrative}».\n\n"
            f"Originating actor cluster: {entity}\n"
            f"Regional focus: {region}\n"
            f"Platform reach estimate: {reach:,} users\n\n"
            f"{_long_text(700)}\n\n"
            f"Content virality score: {round(random.uniform(1.0, 9.9), 1)}/10. "
            f"EUvsDisinfo match: {_pick('confirmed', 'possible', 'not found')}. "
            f"Confidence: {confidence}%.\n"
        )
    elif template == 4:
        # Narrative topology mapping
        body = (
            f"NARRATIVE TOPOLOGY REPORT\n"
            f"ID: DISINFO-{idx:06d}  |  Analyst: {fake_en.name()}\n\n"
            f"Core narrative: «{narrative}»\n"
            f"Originating actor: {entity}\n"
            f"Primary distribution channel: {platform} ({ctype})\n\n"
            f"NARRATIVE VARIANTS OBSERVED\n"
            f"V1: {fake_en.sentence(nb_words=14)}\n"
            f"V2: {fake_en.sentence(nb_words=16)}\n"
            f"V3: {fake_en.sentence(nb_words=13)}\n\n"
            f"AMPLIFICATION ACTORS\n"
            f"{_long_text(500)}\n\n"
            f"Secondary amplifiers include {_pick('domestic far-right pages', 'conspiracy theory accounts', 'state-linked outlets', 'bot clusters')} "
            f"in {_pick('Germany', 'France', 'Italy', 'Poland', 'Romania', 'Hungary')}. "
            f"Total coordinated actors: {fake.random_int(min=50, max=10000)}.\n\n"
            f"COUNTER-NARRATIVE RECOMMENDATIONS\n"
            f"{_para(2)}\n\n"
            f"Reach: {reach:,}  |  Engagements: {engagements:,}  |  Confidence: {confidence}%\n"
        )
    else:
        # Intelligence summary note
        body = (
            f"INTELLIGENCE SUMMARY NOTE\n"
            f"Subject: Disinformation campaign — {narrative[:50]}\n"
            f"Ref: DISINFO-{idx:06d}\n"
            f"Date: {_ts(7)}\n\n"
            f"BACKGROUND\n"
            f"{_long_text(400)}\n\n"
            f"CURRENT ACTIVITY\n"
            f"The narrative «{narrative}» is being actively promoted by {entity} on {platform}. "
            f"Content format: {ctype}. Estimated exposure: {reach:,} users in {region}. "
            f"Engagement rate: {round(engagements/max(reach,1)*100, 2)}%.\n\n"
            f"ORIGIN ANALYSIS\n"
            f"{_long_text(500)}\n\n"
            f"The operational fingerprint is consistent with {entity} campaigns previously documented by "
            f"{_pick('EU DisinfoLab', 'Stanford Internet Observatory', 'DFRLab', 'Oxford Internet Institute')}. "
            f"Attribution confidence: {confidence}%.\n"
        )

    return {
        "title": title, "text": body, "topic": f"narrative: {narrative[:50]}",
        "entity": entity, "platform": platform, "region": region,
        "sentiment": sentiment, "narrative": narrative, "content_type": ctype,
        "platform_reach": reach, "engagements": engagements, "confidence": confidence,
        "analyst": fake_en.name(), "source": "disinformation-monitoring",
        "created_at": _ts(365), "tags": fake.random_elements(DISINFO_NARRATIVES, length=3, unique=True),
    }


# ══════════════════════════════════════════════════════════════════════════════
# 5. GEOPOLITICS
# ══════════════════════════════════════════════════════════════════════════════

GEO_CONFLICTS = [
    "Russia-Ukraine war", "Israel-Hamas conflict", "Taiwan Strait tensions",
    "Sudan civil war", "Sahel instability (Mali, Burkina Faso, Niger)",
    "Armenia-Azerbaijan border dispute", "Serbia-Kosovo standoff",
    "South China Sea territorial dispute", "North Korea missile provocations",
    "Iran nuclear programme escalation", "Turkey-Greece Aegean standoff",
    "Myanmar junta military operations", "Haiti gang-state collapse",
    "Venezuela-Guyana border dispute", "Ethiopia-Eritrea border tensions",
]
GEO_STATE_ACTORS = [
    "Russian Federation (MFA/GRU)", "People's Republic of China (MSS)",
    "Islamic Republic of Iran (IRGC/MOIS)", "Democratic People's Republic of Korea",
    "Turkey (MIT)", "Saudi Arabia (GIP)", "Israel (Mossad/Unit 8200)",
    "United States (CIA/NSA)", "France (DGSE)", "Germany (BND)",
    "United Kingdom (GCHQ/SIS)", "India (RAW)", "Pakistan (ISI)",
    "UAE (SSF)", "Qatar (State Security Bureau)",
]
GEO_REGIONS = [
    "Eastern Europe", "Middle East", "Indo-Pacific", "Sub-Saharan Africa",
    "Central Asia", "Western Balkans", "Arctic", "Latin America", "Horn of Africa",
]
GEO_TOPICS = [
    "military build-up", "diplomatic crisis", "sanctions package",
    "proxy conflict escalation", "intelligence operation disclosure",
    "energy supply weaponisation", "naval incident",
    "cyber attack on state infrastructure", "nuclear posturing",
    "treaty violation", "UN Security Council veto",
    "covert arms transfer", "assassination attempt",
    "disinformation campaign linked to conflict",
]


def generate_geopolitics_doc(idx: int) -> dict:
    conflict   = _pick(*GEO_CONFLICTS)
    actor      = _pick(*GEO_STATE_ACTORS)
    region     = _pick(*GEO_REGIONS)
    escalation = _pick("LOW", "MEDIUM", "HIGH", "CRITICAL")
    topic      = _pick(*GEO_TOPICS)
    sentiment  = _pick(*SENTIMENTS)
    confidence = fake.random_int(min=50, max=98)
    template   = fake.random_int(min=1, max=5)

    title = f"[GEO-{idx:06d}] {conflict} — {topic.title()} — {escalation}"

    if template == 1:
        body = (
            f"GEO-{idx:06d} | CONFIDENTIAL\n"
            f"Conflict: {conflict}\n"
            f"Escalation Level: {escalation}\n\n"
            f"SITUATION UPDATE\n"
            f"Reporting on a {sentiment} {topic} development in the context of {conflict}. "
            f"Actor: {actor}. Region: {region}. Assessment confidence: {confidence}%.\n\n"
            f"INTELLIGENCE ASSESSMENT\n"
            f"{_long_text(700)}\n\n"
            f"DIPLOMATIC IMPLICATIONS\n"
            f"{_para(2)}\n\n"
            f"MILITARY/STRATEGIC POSTURE\n"
            f"Force disposition: "
            f"{_pick('unchanged', 'increased readiness', 'partial mobilisation', 'exercise posture', 'active operations')}. "
            f"{_para(1)}\n"
        )
    elif template == 2:
        body = (
            f"GEOPOLITICAL INTELLIGENCE BRIEF\n"
            f"Reference: GEO-{idx:06d}\n"
            f"Escalation: {escalation} | Region: {region}\n\n"
            f"{conflict}: {topic}\n\n"
            f"{_long_text(600)}\n\n"
            f"Key actor: {actor}. Stated position: {fake_en.sentence(nb_words=15)}. "
            f"Actual intent assessed as: {fake_en.sentence(nb_words=12)}.\n\n"
            f"Third-party reactions:\n"
            f"- {_pick('United States', 'EU', 'NATO', 'China', 'Turkey')}: {fake_en.sentence(nb_words=10)}\n"
            f"- {_pick('United Nations', 'OSCE', 'African Union', 'Arab League')}: {fake_en.sentence(nb_words=10)}\n\n"
            f"Economic indicators: {_pick('energy prices', 'refugee numbers', 'arms imports', 'trade volume')} "
            f"{'rising' if random.random() > 0.5 else 'falling'} {round(random.uniform(5, 40), 1)}% since incident onset.\n\n"
            f"Confidence: {confidence}%.\n"
        )
    elif template == 3:
        body = (
            f"STRATEGIC INTELLIGENCE — {conflict.upper()}\n\n"
            f"ID: GEO-{idx:06d}\n"
            f"Topic: {topic}\n"
            f"Actor assessed: {actor}\n\n"
            f"{_long_text(800)}\n\n"
            f"Escalation risk: {escalation}\n"
            f"Scenario projections:\n"
            f"- Best case: {fake_en.sentence(nb_words=12)}\n"
            f"- Base case: {fake_en.sentence(nb_words=12)}\n"
            f"- Worst case: {fake_en.sentence(nb_words=12)}\n\n"
            f"Regional impact on {region}: {_para(1)}\n"
        )
    elif template == 4:
        # Diplomatic cable style
        body = (
            f"DIPLOMATIC INTELLIGENCE CABLE\n"
            f"Priority: {_pick('FLASH', 'IMMEDIATE', 'PRIORITY', 'ROUTINE')}\n"
            f"Classification: {_pick('SECRET', 'CONFIDENTIAL', 'RESTRICTED')}\n"
            f"Ref: GEO-{idx:06d}\n\n"
            f"Subject: {topic.title()} — {conflict}\n\n"
            f"1. SUMMARY: {actor} has taken {_pick('aggressive', 'defensive', 'ambiguous', 'coercive')} "
            f"posture in the context of {conflict}. Escalation assessed as {escalation}.\n\n"
            f"2. BACKGROUND:\n"
            f"{_long_text(500)}\n\n"
            f"3. ANALYSIS:\n"
            f"{_para(2)}\n\n"
            f"4. IMPLICATIONS FOR {region.upper()}:\n"
            f"{_para(1)}\n\n"
            f"5. RECOMMENDED ACTIONS: Consult allied partners. Review contingency plans for "
            f"{_pick('evacuation', 'sanctions escalation', 'military posturing', 'diplomatic demarche')}. "
            f"Confidence: {confidence}%.\n"
        )
    else:
        # Strategic assessment report
        body = (
            f"STRATEGIC ASSESSMENT REPORT\n"
            f"ID: GEO-{idx:06d}  |  Analyst: {fake_en.name()}  |  Date: {_ts(30)}\n\n"
            f"CONFLICT: {conflict}\n"
            f"PRIMARY ACTOR: {actor}\n"
            f"REGION: {region}\n"
            f"ESCALATION: {escalation}\n\n"
            f"EXECUTIVE SUMMARY\n"
            f"{_long_text(400)}\n\n"
            f"THREAT DYNAMICS\n"
            f"{_long_text(600)}\n\n"
            f"ECONOMIC & HUMANITARIAN IMPACT\n"
            f"{_para(2)}\n\n"
            f"INTELLIGENCE GAPS: {_para(1)}\n"
            f"Confidence overall: {confidence}%\n"
        )

    return {
        "title": title, "text": body, "topic": topic,
        "entity": actor, "platform": "SIGINT/OSINT/HUMINT",
        "region": region, "sentiment": sentiment,
        "conflict": conflict, "state_actor": actor, "escalation_level": escalation,
        "confidence": confidence, "analyst": fake_en.name(),
        "source": "geopolitical-intelligence", "created_at": _ts(365),
        "tags": fake.random_elements(GEO_CONFLICTS, length=3, unique=True),
    }


# ══════════════════════════════════════════════════════════════════════════════
# 6. NARCOTICS TRAFFICKING
# ══════════════════════════════════════════════════════════════════════════════

NARC_SUBSTANCES = [
    "cocaine (HCl)", "fentanyl / carfentanil", "heroin", "MDMA (ecstasy)",
    "methamphetamine", "cannabis (resin)", "cannabis (skunk)",
    "synthetic cannabinoids (Spice)", "ketamine", "nitazenes",
    "GHB/GBL", "LSD analogues", "novel psychoactive substances (NPS)",
    "precursor chemicals (PMK-glycidate)", "counterfeit pharmaceutical opioids",
]
NARC_GROUPS = [
    "Sinaloa Cartel", "CJNG (Jalisco New Generation Cartel)", "Gulf Cartel",
    "Ndrangheta (Calabrian mafia)", "Albanian organised crime group",
    "Moroccan cannabis network", "Dutch synthetic drug production syndicate",
    "Turkish heroin transit network", "Balkan route heroin network",
    "South American FARC-EP dissident cell", "darknet market vendor collective",
    "Serbian crime group",
]
NARC_ROUTES = [
    "South America → West Africa → Europe (cocaine)",
    "Afghanistan → Iran → Turkey → Balkans → Western Europe (heroin)",
    "Mexico → USA border crossing (all substances)",
    "Morocco → Spain → France → Northern Europe (cannabis)",
    "Netherlands → Scandinavia (synthetic drugs)",
    "Pakistan → UK (heroin / cannabis)",
    "China → Mexico → USA (fentanyl precursors)",
    "Darknet: worldwide postal distribution",
    "West Africa → Southern Europe → EU (cocaine)",
]
NARC_MARKETS = [
    "Incognito Market", "AlphaBay successor", "Kingdom Market", "Bohemia Market",
    "Tor2door", "CannaHome", "DeepSea Market", "physical street distribution",
]


def generate_narcotics_doc(idx: int) -> dict:
    substance  = _pick(*NARC_SUBSTANCES)
    group      = _pick(*NARC_GROUPS)
    route      = _pick(*NARC_ROUTES)
    market     = _pick(*NARC_MARKETS)
    platform   = _pick("Telegram", "encrypted darknet market", "Signal", "WhatsApp", "in-person network")
    region     = _pick("Western Europe", "Eastern Europe", "North America", "Latin America", "West Africa", "Balkans")
    seizure_kg = round(random.uniform(0.5, 25_000), 1)
    value_eur  = int(seizure_kg * random.uniform(20_000, 80_000))
    arrests    = fake.random_int(min=0, max=150)
    confidence = fake.random_int(min=50, max=97)
    sentiment  = _pick(*SENTIMENTS)
    template   = fake.random_int(min=1, max=5)

    title = f"[NARC-{idx:06d}] {group} — {substance} — {route[:50]}"

    if template == 1:
        body = (
            f"NARC-{idx:06d} | LAW ENFORCEMENT SENSITIVE\n"
            f"Substance: {substance}\n"
            f"Actor: {group}\n\n"
            f"CASE SUMMARY\n"
            f"Intelligence on {group} trafficking {substance} along the route: {route}. "
            f"Distribution via {market} and {platform}. Region of concern: {region}.\n\n"
            f"SEIZURE DATA\n"
            f"- Quantity seized: {seizure_kg:,.1f} kg\n"
            f"- Estimated street value: €{value_eur:,}\n"
            f"- Arrests: {arrests}\n\n"
            f"OPERATIONAL INTELLIGENCE\n"
            f"{_long_text(600)}\n\n"
            f"FINANCIAL FLOWS\n"
            f"Proceeds laundered through "
            f"{_pick('hawala network', 'cryptocurrency', 'shell companies', 'cash-intensive businesses', 'real estate')}. "
            f"{_para(1)}\n"
        )
    elif template == 2:
        body = (
            f"DRUG TRAFFICKING INTELLIGENCE — {substance.upper()}\n"
            f"File: NARC-{idx:06d} | Confidence: {confidence}%\n\n"
            f"Network: {group}\n"
            f"Route: {route}\n"
            f"End market: {region}\n\n"
            f"{_long_text(700)}\n\n"
            f"OPSEC of the group assessed as "
            f"{_pick('high', 'medium', 'low')}. Communication via {platform}. "
            f"Darknet presence: {market}.\n\n"
            f"Purity: {fake.random_int(min=40, max=97)}%. "
            f"Price per kg (wholesale): €{fake.random_int(min=5000, max=80000):,}.\n\n"
            f"Supply chain vulnerabilities: {_para(1)}\n"
        )
    elif template == 3:
        body = (
            f"ORGANISED CRIME — NARCOTICS INTELLIGENCE\n\n"
            f"Reference: NARC-{idx:06d}\n"
            f"Group: {group}\n"
            f"Commodity: {substance}\n"
            f"Route: {route}\n\n"
            f"{_long_text(700)}\n\n"
            f"Law enforcement action: {arrests} arrests, {seizure_kg:,.1f} kg seized (€{value_eur:,}).\n\n"
            f"Threat assessment: {_pick('HIGH', 'MEDIUM', 'ESCALATING')} — group shows "
            f"{_pick('resilience', 'fragmentation', 'expansion', 'reorientation')} following recent pressure.\n\n"
            f"{_para(1)}\n"
        )
    elif template == 4:
        # Supply chain analysis
        body = (
            f"SUPPLY CHAIN ANALYSIS REPORT\n"
            f"Case: NARC-{idx:06d}  |  Analyst: {fake_en.name()}\n\n"
            f"Commodity: {substance}\n"
            f"Controlling network: {group}\n\n"
            f"PRODUCTION / PROCUREMENT\n"
            f"{_long_text(400)}\n\n"
            f"TRANSPORTATION\n"
            f"Route: {route}\n"
            f"Transit method: {_pick('maritime container', 'air freight', 'overland vehicle', 'postal parcels', 'body packing', 'drone drop')}\n"
            f"Concealment: {_pick('false compartment', 'legitimate cargo co-mingling', 'liquid impregnation', 'compressed blocks', 'couriers')}\n\n"
            f"DISTRIBUTION IN {region.upper()}\n"
            f"{_long_text(400)}\n\n"
            f"Platform used: {platform}  |  Darknet presence: {market}\n"
            f"Retail value in {region}: €{value_eur:,} for {seizure_kg:,.1f} kg.\n"
            f"Seizures this period: {arrests} arrests, {seizure_kg:,.1f} kg.\n"
        )
    else:
        # Intelligence note
        body = (
            f"INTELLIGENCE NOTE — NARCOTICS\n"
            f"Ref: NARC-{idx:06d}  |  Priority: {_pick('HIGH', 'MEDIUM', 'ROUTINE')}\n\n"
            f"Summary: {group} has been identified as the controlling entity for {substance} "
            f"trafficking along the {route} corridor.\n\n"
            f"{_long_text(800)}\n\n"
            f"Financial intelligence confirms approximately €{value_eur:,} in proceeds "
            f"from {seizure_kg:,.1f} kg of {substance}. "
            f"Money laundering via {_pick('cryptocurrency', 'hawala', 'real estate', 'cash-intensive SMEs')} confirmed. "
            f"Confidence: {confidence}%. Arrests to date: {arrests}.\n"
        )

    return {
        "title": title, "text": body, "topic": f"{substance} trafficking",
        "entity": group, "platform": platform, "region": region,
        "sentiment": sentiment, "substance": substance, "route": route,
        "darknet_market": market, "seizure_kg": seizure_kg, "value_eur": value_eur,
        "arrests": arrests, "confidence": confidence,
        "analyst": fake_en.name(), "source": "narcotics-intelligence",
        "created_at": _ts(365), "tags": fake.random_elements(NARC_SUBSTANCES, length=3, unique=True),
    }


# ══════════════════════════════════════════════════════════════════════════════
# 7. TERRORISM & EXTREMISM
# ══════════════════════════════════════════════════════════════════════════════

TERROR_GROUPS = [
    "Islamic State (ISIS/Daesh)", "al-Qaeda affiliates (AQ-AP, AQIM)",
    "Hay'at Tahrir al-Sham (HTS)", "Hamas military wing (Qassam Brigades)",
    "Hezbollah external operations", "Boko Haram / ISWAP",
    "al-Shabaab", "Right-wing accelerationist network",
    "Far-right lone-actor cell", "Eco-extremist group (ELF affiliate)",
    "Incel radicalisation network", "Wagner-linked mercenary cell",
    "CIRA (Continuity IRA)", "PKK militant cell",
    "Left-wing anarchist sabotage cell",
]
TERROR_IDEOLOGIES = [
    "Salafi-jihadist", "neo-Nazi / accelerationist", "far-right ethnonationalist",
    "incel / misogynist extremism", "eco-terrorism", "left-wing anarchism",
    "separatist / irredentist", "religious millenarianism", "anti-government militarism",
]
TERROR_TARGETS = [
    "critical national infrastructure", "mass gathering event",
    "government building / official", "religious site",
    "transport hub", "military installation", "journalist / media outlet",
    "ethnic minority community", "LGBTQ+ venue", "financial institution",
]
TERROR_PLATFORMS = ["Telegram", "RocketChat", "Matrix/Element", "darkweb forum", "encrypted P2P app"]
TERROR_REGIONS = [
    "Western Europe", "Middle East", "Sub-Saharan Africa",
    "South Asia", "North Africa", "Sahel", "North America",
]


def generate_terrorism_doc(idx: int) -> dict:
    group      = _pick(*TERROR_GROUPS)
    ideology   = _pick(*TERROR_IDEOLOGIES)
    target     = _pick(*TERROR_TARGETS)
    platform   = _pick(*TERROR_PLATFORMS)
    region     = _pick(*TERROR_REGIONS)
    threat_lvl = _pick("LOW", "MODERATE", "SUBSTANTIAL", "SEVERE", "CRITICAL")
    confidence = fake.random_int(min=40, max=98)
    sentiment  = _pick(*SENTIMENTS)
    members    = fake.random_int(min=1, max=500)
    template   = fake.random_int(min=1, max=5)

    title = f"[TERROR-{idx:06d}] {group} — {ideology} — {region}"

    if template == 1:
        body = (
            f"TERROR-{idx:06d} | SECRET\n"
            f"Threat Level: {threat_lvl}\n"
            f"Group: {group}\n"
            f"Ideology: {ideology}\n\n"
            f"THREAT SUMMARY\n"
            f"Intelligence indicates {group} ({ideology}) is planning or conducting operations "
            f"targeting {target} in {region}. "
            f"Active membership: approximately {members}. Primary comms channel: {platform}.\n\n"
            f"RADICALISATION PATHWAY\n"
            f"{_long_text(600)}\n\n"
            f"OPERATIONAL INDICATORS\n"
            f"- {_pick('Surveillance of target sites', 'Weapons procurement', 'Explosives precursor purchase', 'Travel to conflict zone', 'Encrypted communications spike')}\n"
            f"- {_pick('Online recruitment increase', 'Propaganda distribution uptick', 'Fundraising via crypto', 'Support network activation')}\n\n"
            f"FINANCING\n"
            f"{_para(1)} "
            f"Estimated annual budget: ${fake.random_int(min=5000, max=2_000_000):,}.\n"
        )
    elif template == 2:
        body = (
            f"COUNTER-TERRORISM INTELLIGENCE\n"
            f"Reference: TERROR-{idx:06d} | Threat: {threat_lvl}\n\n"
            f"Subject organisation: {group}\n"
            f"Ideological basis: {ideology}\n"
            f"Target type: {target}\n\n"
            f"{_long_text(700)}\n\n"
            f"Online presence: active on {platform} with {fake.random_int(min=100, max=50000):,} followers. "
            f"Content type: {_pick('attack planning manuals', 'recruitment videos', 'propaganda', 'bomb-making instructions', 'target lists')}.\n\n"
            f"Financing: {_pick('self-funded', 'state-sponsored', 'crowd-funded via crypto', 'criminal enterprise-linked', 'diaspora donations')}.\n"
            f"Confidence: {confidence}%.\n"
        )
    elif template == 3:
        body = (
            f"EXTREMISM MONITORING — {ideology.upper()}\n\n"
            f"ID: TERROR-{idx:06d}\n"
            f"Actor: {group}\n"
            f"Region: {region}\n\n"
            f"{_long_text(700)}\n\n"
            f"The group has issued {_pick('implicit', 'explicit', 'coded')} threats against {target}. "
            f"Online activity on {platform} has increased {fake.random_int(min=20, max=400)}% over the past 30 days.\n\n"
            f"Threat level: {threat_lvl}\n"
            f"Members / followers: ~{members}\n"
            f"Financing: {fake_en.sentence(nb_words=12)}\n\n"
            f"{_para(1)} Confidence: {confidence}%.\n"
        )
    elif template == 4:
        # Radicalisation case study
        body = (
            f"RADICALISATION CASE STUDY\n"
            f"Reference: TERROR-{idx:06d}  |  Classification: SECRET\n\n"
            f"SUBJECT PROFILE\n"
            f"Affiliated with: {group}\n"
            f"Ideology: {ideology}\n"
            f"Region: {region}\n"
            f"Membership: ~{members} active operatives\n\n"
            f"PATHWAY TO RADICALISATION\n"
            f"{_long_text(600)}\n\n"
            f"ONLINE ACTIVITY\n"
            f"Primary platform: {platform}\n"
            f"Content produced: {_pick('attack tutorials', 'recruitment propaganda', 'ideological manifestos', 'incitement videos')}\n"
            f"Reach: {fake.random_int(min=200, max=100000):,} subscribers / followers\n\n"
            f"THREAT ASSESSMENT\n"
            f"Threat level: {threat_lvl}. Target category: {target}. "
            f"{_para(1)} Confidence: {confidence}%.\n"
        )
    else:
        # Operational alert
        body = (
            f"OPERATIONAL THREAT ALERT\n"
            f"Alert ID: TERROR-{idx:06d}\n"
            f"Priority: {threat_lvl}\n"
            f"Date: {_ts(7)}\n\n"
            f"Threat actor {group} ({ideology}) has been assessed as an imminent threat to {target} "
            f"in {region}. Intelligence sources confirm operational planning is in {_pick('early', 'advanced', 'final')} stages.\n\n"
            f"{_long_text(800)}\n\n"
            f"Current group strength: {members} operatives. Financing: "
            f"${fake.random_int(min=5000, max=500000):,} available. "
            f"Primary communication on {platform}. "
            f"Confidence: {confidence}%.\n\n"
            f"IMMEDIATE ACTIONS REQUIRED:\n"
            f"- Notify national CT authority.\n"
            f"- Increase protection level at {target} facilities.\n"
            f"- Coordinate with {_pick('Europol', 'FBI', 'MI5', 'BfV', 'DGSI')} counterparts.\n"
        )

    return {
        "title": title, "text": body, "topic": f"{ideology} extremism",
        "entity": group, "platform": platform, "region": region,
        "sentiment": sentiment, "ideology": ideology, "target_type": target,
        "threat_level": threat_lvl, "member_count": members, "confidence": confidence,
        "analyst": fake_en.name(), "source": "counter-terrorism-intelligence",
        "created_at": _ts(365), "tags": fake.random_elements(TERROR_IDEOLOGIES, length=3, unique=True),
    }


# ══════════════════════════════════════════════════════════════════════════════
# 8. HUMAN TRAFFICKING & SMUGGLING
# ══════════════════════════════════════════════════════════════════════════════

HT_GROUPS = [
    "Albanian Organised Crime Network", "Nigerian trafficking syndicate (JJC/Black Axe)",
    "Vietnamese nail bar network (UK)", "Chinese snakehead organisation",
    "Belarusian state-facilitated migration push", "Libyan coast militia",
    "Turkish people-smuggling network", "Romanian exploitation network (UK/Germany)",
    "Syrian refugee exploitation cell", "Iraqi Kurdish smuggling network",
    "Cameroonian trafficking cell", "Southeast Asian labour exploitation syndicate",
]
HT_ROUTES = [
    "Libya → Malta/Italy → Northern Europe (Mediterranean route)",
    "Turkey → Greece → Balkans → Western Europe (Balkan route)",
    "Belarus → Poland/Lithuania → Western Europe (Eastern border route)",
    "Morocco → Spain (Strait of Gibraltar / Canary Islands)",
    "Sahel → Libya → Mediterranean",
    "Central America → Mexico → United States (land route)",
    "Southeast Asia → Middle East (labour exploitation route)",
    "Eastern Europe → Western Europe (intra-EU exploitation)",
    "West Africa → North Africa → Europe",
]
HT_RECRUIT_METHODS = [
    "fake job advertising on Facebook", "romance scam recruitment",
    "false asylum promise", "debt bondage scheme",
    "social media modelling scam", "forced marriage arrangement",
    "in-person recruitment in origin country",
    "encrypted app (Telegram/WhatsApp) solicitation",
    "fake EU work permit offer",
]
HT_EXPLOITATION_TYPES = [
    "sexual exploitation", "forced labour (agriculture)", "forced labour (construction)",
    "domestic servitude", "forced criminality", "organ trafficking",
    "forced begging networks", "forced marriage",
]


def generate_trafficking_doc(idx: int) -> dict:
    group      = _pick(*HT_GROUPS)
    route      = _pick(*HT_ROUTES)
    recruit    = _pick(*HT_RECRUIT_METHODS)
    platform   = _pick("Facebook", "Instagram", "Telegram", "WhatsApp", "TikTok", "darkweb forum")
    region     = _pick("Mediterranean", "Western Europe", "Eastern Europe", "West Africa", "Southeast Asia", "Latin America")
    exploit    = _pick(*HT_EXPLOITATION_TYPES)
    victims    = fake.random_int(min=2, max=2000)
    profit_eur = fake.random_int(min=10_000, max=5_000_000)
    confidence = fake.random_int(min=50, max=97)
    sentiment  = _pick(*SENTIMENTS)
    template   = fake.random_int(min=1, max=5)

    title = f"[HTRAF-{idx:06d}] {group} — {exploit} — {route[:50]}"

    if template == 1:
        body = (
            f"HTRAF-{idx:06d} | LAW ENFORCEMENT RESTRICTED\n"
            f"Exploitation type: {exploit}\n"
            f"Actor: {group}\n\n"
            f"CASE SUMMARY\n"
            f"Intelligence on {group} engaged in {exploit} along route: {route}. "
            f"Recruitment via {recruit} on {platform}. Estimated victims: {victims}. Region: {region}.\n\n"
            f"RECRUITMENT & CONTROL METHODS\n"
            f"{_long_text(600)}\n"
            f"Debt bondage of approximately €{fake.random_int(min=1000, max=30000):,} per victim is used to maintain control.\n\n"
            f"FINANCIAL INTELLIGENCE\n"
            f"Estimated group revenue: €{profit_eur:,} annually. "
            f"Laundered through {_pick('hair salons', 'nail bars', 'restaurants', 'cash-intensive retail', 'cryptocurrency')}. "
            f"{_para(1)}\n\n"
            f"VICTIM PROFILE\n"
            f"Primary origin countries: {_pick('Albania', 'Nigeria', 'Vietnam', 'Romania', 'Syria', 'Eritrea', 'Cambodia')}. "
            f"Age range: {fake.random_int(min=14, max=40)}–{fake.random_int(min=20, max=50)} years.\n"
        )
    elif template == 2:
        body = (
            f"ANTI-TRAFFICKING INTELLIGENCE BRIEF\n"
            f"Reference: HTRAF-{idx:06d} | Confidence: {confidence}%\n\n"
            f"Network: {group}\n"
            f"Route: {route}\n"
            f"Exploitation: {exploit}\n\n"
            f"{_long_text(700)}\n\n"
            f"Victims identified: {victims}. Recruitment method: {recruit}.\n"
            f"Communications via {platform}. Financial flows: €{profit_eur:,} estimated.\n\n"
            f"Border crossing method: {_pick('forged documents', 'lorry concealment', 'rubber dinghy', 'legitimate visa overstay', 'corrupt border official')}.\n\n"
            f"{_para(1)}\n"
        )
    elif template == 3:
        body = (
            f"HUMAN TRAFFICKING NETWORK ASSESSMENT\n\n"
            f"ID: HTRAF-{idx:06d}\n"
            f"Group: {group}\n"
            f"Primary exploitation type: {exploit}\n\n"
            f"{_long_text(800)}\n\n"
            f"Route: {route}\n"
            f"Recruitment method: {recruit} via {platform}\n"
            f"Estimated victims: {victims}\n"
            f"Annual profit: €{profit_eur:,}\n\n"
            f"Threat assessment: {_para(1)}\n"
        )
    elif template == 4:
        # Survivor testimony analysis
        body = (
            f"SURVIVOR TESTIMONY ANALYSIS\n"
            f"Case: HTRAF-{idx:06d}  |  Classification: RESTRICTED\n\n"
            f"Based on interviews with {fake.random_int(min=1, max=50)} survivors of {exploit} "
            f"linked to {group}.\n\n"
            f"ROUTE TAKEN\n"
            f"{route}\n\n"
            f"RECRUITMENT NARRATIVE\n"
            f"{_long_text(500)}\n\n"
            f"The primary recruitment method was {recruit}, conducted through {platform}. "
            f"Victims were promised {_pick('legitimate employment', 'asylum support', 'education opportunities', 'modelling contracts')} "
            f"before being subjected to {exploit}.\n\n"
            f"NETWORK STRUCTURE\n"
            f"{_long_text(400)}\n\n"
            f"Network hierarchy: {_pick('cell-based', 'franchise model', 'family-run', 'cartel-affiliated')}. "
            f"Estimated members: {fake.random_int(min=5, max=500)}. "
            f"Annual profit: €{profit_eur:,}. Confidence: {confidence}%.\n"
        )
    else:
        # Law enforcement brief
        body = (
            f"LAW ENFORCEMENT BRIEF — HUMAN TRAFFICKING\n"
            f"File: HTRAF-{idx:06d}  |  Date: {_ts(30)}\n\n"
            f"Suspect network: {group}\n"
            f"Primary offence: {exploit}\n"
            f"Region of operation: {region}\n\n"
            f"{_long_text(700)}\n\n"
            f"Victims: {victims} identified ({_pick('direct interviews', 'NGO referrals', 'border interceptions', 'police rescue')}). "
            f"Route confirmed: {route}.\n\n"
            f"INTELLIGENCE VALUE\n"
            f"This network provides a significant intelligence opportunity. {_para(1)}\n\n"
            f"Joint operation recommended with {_pick('Europol', 'IOM', 'UNHCR', 'Interpol', 'national border police')}. "
            f"Confidence: {confidence}%.\n"
        )

    return {
        "title": title, "text": body, "topic": exploit,
        "entity": group, "platform": platform, "region": region,
        "sentiment": sentiment, "route": route, "recruitment_method": recruit,
        "exploitation_type": exploit, "victim_count": victims, "profit_eur": profit_eur,
        "confidence": confidence, "analyst": fake_en.name(),
        "source": "anti-trafficking-intelligence", "created_at": _ts(365),
        "tags": fake.random_elements(HT_EXPLOITATION_TYPES, length=3, unique=True),
    }


# ══════════════════════════════════════════════════════════════════════════════
# 9. CLIMATE & ENVIRONMENTAL DISINFORMATION
# ══════════════════════════════════════════════════════════════════════════════

CLIMATE_NARRATIVES = [
    "climate change is a natural cycle unrelated to human activity",
    "electric vehicles cause more emissions than combustion engines",
    "wind farms kill more birds than fossil fuels",
    "solar panels cannot produce enough energy to replace oil",
    "the Green Deal will destroy European industrial jobs",
    "climate scientists falsify data for research funding",
    "Net Zero targets are an elite depopulation agenda",
    "carbon taxes are a wealth transfer to the global elite",
    "renewables are less reliable and more expensive than nuclear or gas",
    "COP climate summits are controlled by WEF and billionaire donors",
    "IPCC reports omit positive effects of CO2 increase on plant growth",
    "geoengineering chemtrails are already deployed without public consent",
    "environmental NGOs are funded by foreign governments to weaken industry",
    "fossil fuel companies are already planting billions of trees secretly",
]
CLIMATE_BACKERS = [
    "major oil & gas conglomerate (via dark-money PAC)",
    "petrostate strategic communications arm",
    "coal industry lobby (EU)",
    "anonymous funding via Cayman Islands foundation",
    "steel & heavy industry lobby group",
    "automobile manufacturer consortium",
    "agricultural lobby against methane regulation",
]
CLIMATE_PLATFORMS = ["YouTube", "Twitter/X", "Facebook", "Substack", "Rumble", "podcast network"]
CLIMATE_REGIONS = ["European Union", "United States", "Australia", "Global", "United Kingdom", "Germany"]
CLIMATE_CONTENT_TYPES = [
    "pseudo-scientific article", "viral meme campaign", "sponsored documentary",
    "bot-amplified hashtag", "fake scientist profile", "think-tank report",
    "deep-fake expert testimony", "cherry-picked data visualisation",
]


def generate_climate_doc(idx: int) -> dict:
    narrative  = _pick(*CLIMATE_NARRATIVES)
    backer     = _pick(*CLIMATE_BACKERS)
    platform   = _pick(*CLIMATE_PLATFORMS)
    region     = _pick(*CLIMATE_REGIONS)
    ctype      = _pick(*CLIMATE_CONTENT_TYPES)
    reach      = fake.random_int(min=5000, max=20_000_000)
    confidence = fake.random_int(min=45, max=95)
    sentiment  = _pick(*SENTIMENTS)
    template   = fake.random_int(min=1, max=5)

    title = f"[CLIMATE-{idx:06d}] Disinfo: «{narrative[:55]}»"

    if template == 1:
        body = (
            f"CLIMATE-{idx:06d} | TLP:WHITE\n"
            f"Narrative: {narrative}\n"
            f"Content type: {ctype}\n\n"
            f"SUMMARY\n"
            f"A {sentiment} {ctype} promoting the narrative «{narrative}» has been detected on {platform}, "
            f"reaching approximately {reach:,} users in {region}. "
            f"Industry backer assessed as: {backer}.\n\n"
            f"CONTENT ANALYSIS\n"
            f"{_long_text(600)}\n\n"
            f"FUNDING TRAIL\n"
            f"{_para(1)} Funding traced to {backer} via "
            f"{_pick('shell foundation', 'dark-money PAC', 'think-tank grants', 'advertising spend')}.\n\n"
            f"SCIENTIFIC CONSENSUS\n"
            f"IPCC AR6 directly contradicts this claim. "
            f"Debunked by {_pick('Climate Feedback', 'FactCheck.org', 'Carbon Brief', 'Skeptical Science')}.\n"
        )
    elif template == 2:
        body = (
            f"ENVIRONMENTAL DISINFORMATION MONITOR\n"
            f"ID: CLIMATE-{idx:06d} | Region: {region}\n\n"
            f"Detected narrative: «{narrative}»\n"
            f"Distribution: {ctype} on {platform}\n"
            f"Estimated reach: {reach:,} users\n\n"
            f"{_long_text(700)}\n\n"
            f"The campaign aligns with interests of {backer}. "
            f"Timing correlates with {_pick('COP summit', 'EU ETS vote', 'Green Deal legislation', 'IPCC report release')}.\n\n"
            f"Scientific accuracy: {_pick('0/10 — completely false', '2/10 — misleading', '4/10 — missing context')}.\n"
            f"Confidence: {confidence}%.\n"
        )
    elif template == 3:
        body = (
            f"CLIMATE DISINFORMATION INTELLIGENCE\n\n"
            f"ID: CLIMATE-{idx:06d}\n"
            f"Narrative: «{narrative}»\n"
            f"Backer: {backer}\n\n"
            f"{_long_text(700)}\n\n"
            f"Platform: {platform} | Content type: {ctype}\n"
            f"Reach: {reach:,} | Region: {region}\n\n"
            f"Policy impact: {_pick('Low', 'Medium', 'High')} — "
            f"narrative is {_pick('gaining', 'losing', 'maintaining')} traction.\n\n"
            f"{_para(1)}\n"
        )
    elif template == 4:
        # Funding network analysis
        body = (
            f"FUNDING NETWORK ANALYSIS — CLIMATE DISINFO\n"
            f"Case: CLIMATE-{idx:06d}  |  Analyst: {fake_en.name()}\n\n"
            f"Narrative under investigation: «{narrative}»\n\n"
            f"FINANCIAL ORIGINS\n"
            f"{_long_text(500)}\n\n"
            f"Funding traced from {backer} through the following chain:\n"
            f"  Industry donor → {_pick('Cayman foundation', 'Delaware LLC', 'Swiss association')} → "
            f"{_pick('think-tank', 'advocacy group', 'media outlet', 'social media influencer network')}\n\n"
            f"AMPLIFICATION STRATEGY\n"
            f"Content type: {ctype} distributed via {platform}. "
            f"Reach: {reach:,} in {region}. "
            f"{_para(1)}\n\n"
            f"Attribution confidence: {confidence}%.\n"
        )
    else:
        # Rapid assessment
        body = (
            f"RAPID ASSESSMENT — CLIMATE NARRATIVE\n"
            f"ID: CLIMATE-{idx:06d}  |  Date: {_ts(7)}\n\n"
            f"A {ctype} spreading the narrative «{narrative}» has gone viral on {platform} in {region}. "
            f"The content has reached {reach:,} users and is growing.\n\n"
            f"{_long_text(700)}\n\n"
            f"The narrative is assessed as {_pick('completely fabricated', 'misleading via selective facts', 'out-of-context', 'sophisticated disinformation')}. "
            f"Backing entity: {backer}. "
            f"Counter-narrative urgency: {_pick('HIGH — action needed within 24h', 'MEDIUM — monitor and prepare', 'LOW — track for escalation')}.\n\n"
            f"Confidence: {confidence}%.\n"
        )

    return {
        "title": title, "text": body, "topic": f"climate disinfo: {narrative[:40]}",
        "entity": backer, "platform": platform, "region": region,
        "sentiment": sentiment, "narrative": narrative, "content_type": ctype,
        "industry_backer": backer, "platform_reach": reach, "confidence": confidence,
        "analyst": fake_en.name(), "source": "climate-disinformation-monitor",
        "created_at": _ts(365), "tags": fake.random_elements(CLIMATE_NARRATIVES, length=3, unique=True),
    }


# ══════════════════════════════════════════════════════════════════════════════
# 10. HEALTH DISINFORMATION & BIO THREATS
# ══════════════════════════════════════════════════════════════════════════════

HEALTH_TOPICS = [
    "COVID-19 vaccine side effects exaggeration", "anti-vaccine movement coordination",
    "5G / microchip vaccine conspiracy", "mRNA vaccine DNA alteration claim",
    "ivermectin / hydroxychloroquine misinformation", "WHO suppression conspiracy",
    "lab-leak theory (engineered bioweapon narrative)", "mpox outbreak conspiracy",
    "flu vaccine autism link revival", "alternative cancer cure fraud",
    "pandemic preparedness treaty opposition",
    "bioweapon development allegation (US / China)", "pandemic simulation as preplanning evidence",
    "fertility harm from COVID vaccination", "mass die-off prediction (vaccines)",
]
HEALTH_ACTORS = [
    "Russian state health disinfo network (Doppelgänger offshoot)",
    "Chinese MFA WeChat disinformation cluster",
    "domestic anti-vaccine influencer network",
    "alternative medicine product company",
    "far-right extremist health platform",
    "anonymous Telegram anti-vax channel cluster",
    "pseudo-scientific foundation (US-based)",
    "Iranian IRGC health narrative unit",
]
HEALTH_PLATFORMS = ["Telegram", "Facebook", "YouTube", "Substack", "Twitter/X", "TikTok", "podcast network"]
HEALTH_REGIONS = ["Global", "United States", "Western Europe", "Eastern Europe", "Sub-Saharan Africa", "Latin America"]
HEALTH_CLAIM_TYPES = [
    "fabricated statistics", "misrepresented study", "false expert citation",
    "anecdotal adverse event amplification", "cherry-picked trial data",
    "fabricated government document leak", "deepfake medical professional testimony",
]


def generate_health_doc(idx: int) -> dict:
    topic      = _pick(*HEALTH_TOPICS)
    actor      = _pick(*HEALTH_ACTORS)
    platform   = _pick(*HEALTH_PLATFORMS)
    region     = _pick(*HEALTH_REGIONS)
    claim_type = _pick(*HEALTH_CLAIM_TYPES)
    reach      = fake.random_int(min=1000, max=30_000_000)
    confidence = fake.random_int(min=45, max=97)
    sentiment  = _pick(*SENTIMENTS)
    template   = fake.random_int(min=1, max=5)

    title = f"[HEALTH-{idx:06d}] Disinfo: {topic[:60]} — {platform}"

    if template == 1:
        body = (
            f"HEALTH-{idx:06d} | TLP:WHITE\n"
            f"Topic: {topic}\n"
            f"False claim type: {claim_type}\n\n"
            f"SUMMARY\n"
            f"A {sentiment} health disinformation campaign promoting «{topic}» has been detected on {platform}. "
            f"Actor: {actor}. Region: {region}. Estimated reach: {reach:,}.\n\n"
            f"CONTENT ANALYSIS\n"
            f"{_long_text(600)}\n\n"
            f"PUBLIC HEALTH IMPACT\n"
            f"The campaign has been linked to a {fake.random_int(min=5, max=40)}% decline in "
            f"{_pick('vaccination uptake', 'treatment compliance', 'testing rates', 'trust in health institutions')} "
            f"in affected communities. {_para(1)}\n\n"
            f"ATTRIBUTION\n"
            f"Attributed to {actor} with {confidence}% confidence. "
            f"{_para(1)}\n\n"
            f"DEBUNKING\n"
            f"Refuted by {_pick('WHO', 'CDC', 'ECDC', 'EMA', 'MHRA', 'peer-reviewed meta-analysis in Lancet')}. "
            f"Viral coefficient: {round(random.uniform(1.2, 7.5), 2)}.\n"
        )
    elif template == 2:
        body = (
            f"PUBLIC HEALTH SECURITY ALERT\n"
            f"Reference: HEALTH-{idx:06d} | Confidence: {confidence}%\n\n"
            f"Disinformation topic: {topic}\n"
            f"Actor: {actor}\n"
            f"Platform: {platform} | Region: {region}\n\n"
            f"{_long_text(700)}\n\n"
            f"Claim type: {claim_type}. "
            f"Content shared {fake.random_int(min=500, max=5_000_000):,} times. "
            f"Linked to {fake.random_int(min=1, max=50)} reported cases of delayed medical treatment.\n\n"
            f"Scientific consensus: CONTRADICTED BY EVIDENCE.\n"
            f"Fact-check status: {_pick('confirmed false', 'misleading', 'missing context', 'unverifiable')} "
            f"by {_pick('Full Fact', 'PolitiFact', 'AFP Fact Check', 'Reuters Fact Check')}.\n"
        )
    elif template == 3:
        body = (
            f"HEALTH DISINFORMATION MONITORING — {platform.upper()}\n\n"
            f"ID: HEALTH-{idx:06d}\n"
            f"Topic: {topic}\n"
            f"Actor: {actor}\n\n"
            f"{_long_text(700)}\n\n"
            f"Claim type: {claim_type}\n"
            f"Platform reach: {reach:,}\n"
            f"Region: {region}\n\n"
            f"Potential harm: "
            f"{_pick('vaccine hesitancy increase', 'treatment refusal', 'panic buying of unproven products', 'violence against health workers', 'erosion of institutional trust')}.\n\n"
            f"{_para(1)} Confidence: {confidence}%.\n"
        )
    elif template == 4:
        # Epidemiological impact assessment
        body = (
            f"EPIDEMIOLOGICAL IMPACT ASSESSMENT\n"
            f"Case: HEALTH-{idx:06d}  |  Analyst: {fake_en.name()}\n\n"
            f"Disinformation campaign: «{topic}»\n"
            f"Source actor: {actor}\n"
            f"Primary platform: {platform}\n\n"
            f"CAMPAIGN CHARACTERISTICS\n"
            f"Claim type: {claim_type}\n"
            f"Reach: {reach:,} users in {region}\n"
            f"Peak virality: {_ts(30)}\n\n"
            f"HEALTH SYSTEM IMPACT\n"
            f"{_long_text(600)}\n\n"
            f"Modelled impact: {fake.random_int(min=100, max=100000):,} individuals potentially influenced to "
            f"{_pick('refuse vaccination', 'self-medicate with unproven treatments', 'avoid hospitals', 'spread false information')}. "
            f"Estimated excess mortality risk: {round(random.uniform(0.01, 2.5), 2)}%.\n\n"
            f"Attribution: {actor}. Confidence: {confidence}%.\n"
        )
    else:
        # Rapid response note
        body = (
            f"RAPID RESPONSE INTELLIGENCE NOTE — HEALTH DISINFO\n"
            f"ID: HEALTH-{idx:06d}  |  Priority: {_pick('URGENT', 'HIGH', 'STANDARD')}\n\n"
            f"«{topic}» is spreading rapidly on {platform} in {region}, originating from {actor}.\n\n"
            f"{_long_text(800)}\n\n"
            f"Reach: {reach:,}. Claim basis: {claim_type}. "
            f"The narrative is {_pick('completely false', 'dangerously misleading', 'technically accurate but used deceptively', 'cherry-picked from legitimate research')}. "
            f"Refuted by {_pick('WHO', 'CDC', 'BMJ', 'Lancet editorial', 'national health authority')}.\n\n"
            f"Response recommendation: {_pick('Immediate counter-messaging', 'Platform takedown request', 'Coordination with health ministry', 'Influencer briefing programme')}. "
            f"Confidence: {confidence}%.\n"
        )

    return {
        "title": title, "text": body, "topic": topic,
        "entity": actor, "platform": platform, "region": region,
        "sentiment": sentiment, "health_topic": topic, "false_claim_type": claim_type,
        "platform_reach": reach, "confidence": confidence,
        "analyst": fake_en.name(), "source": "health-disinformation-monitor",
        "created_at": _ts(365), "tags": fake.random_elements(HEALTH_TOPICS, length=3, unique=True),
    }


# ══════════════════════════════════════════════════════════════════════════════
# Index registry & runner
# ══════════════════════════════════════════════════════════════════════════════

INDICES: dict[str, dict] = {
    "ro_elections":    {"index": "qsint_docs_ro_elections",    "fn": generate_ro_elections_doc},
    "cybersecurity":   {"index": "qsint_docs_cybersecurity",   "fn": generate_cybersecurity_doc},
    "financial_crime": {"index": "qsint_docs_financial_crime", "fn": generate_financial_crime_doc},
    "disinformation":  {"index": "qsint_docs_disinformation",  "fn": generate_disinformation_doc},
    "geopolitics":     {"index": "qsint_docs_geopolitics",     "fn": generate_geopolitics_doc},
    "narcotics":       {"index": "qsint_docs_narcotics",       "fn": generate_narcotics_doc},
    "terrorism":       {"index": "qsint_docs_terrorism",       "fn": generate_terrorism_doc},
    "trafficking":     {"index": "qsint_docs_trafficking",     "fn": generate_trafficking_doc},
    "climate":         {"index": "qsint_docs_climate",         "fn": generate_climate_doc},
    "health":          {"index": "qsint_docs_health",          "fn": generate_health_doc},
}


def bulk_index(client: ESClient, docs: list[dict], index_name: str) -> tuple[int, int]:
    actions = [{"_index": index_name, "_id": str(uuid.uuid4()), "_source": doc} for doc in docs]
    ok, errors = bulk(client._client, actions, raise_on_error=False)
    return ok, len(errors)


def main():
    parser = argparse.ArgumentParser(description="Seed 10 themed intelligence Elasticsearch indices")
    parser.add_argument("--count",   type=int, default=10_000,
                        help="Docs per index (default: 10000)")
    parser.add_argument("--batch",   type=int, default=500,
                        help="Bulk batch size (default: 500)")
    parser.add_argument("--clear",   action="store_true",
                        help="Delete and recreate index before seeding")
    parser.add_argument("--indices", type=str, default="",
                        help=(
                            "Comma-separated subset to seed. "
                            "Available: " + ", ".join(INDICES.keys())
                        ))
    args = parser.parse_args()

    client = ESClient()
    if not client.test_connection():
        print("ERROR: Cannot connect to Elasticsearch.")
        sys.exit(1)

    selected = (
        [k.strip() for k in args.indices.split(",") if k.strip()]
        if args.indices else list(INDICES.keys())
    )
    unknown = [k for k in selected if k not in INDICES]
    if unknown:
        print(f"ERROR: Unknown indices: {unknown}\nAvailable: {list(INDICES.keys())}")
        sys.exit(1)

    print(
        f"Seeding {len(selected)} index/indices × {args.count:,} docs each "
        f"(batch={args.batch}, clear={args.clear})\n"
    )

    for key in selected:
        cfg        = INDICES[key]
        index_name = cfg["index"]
        gen_fn     = cfg["fn"]

        if args.clear:
            try:
                client._client.indices.delete(index=index_name)
                print(f"  Deleted '{index_name}'")
            except Exception:
                pass

        client.ensure_index(index_name=index_name)

        total_ok = total_err = 0
        print(f"▶  {index_name}  ({args.count:,} docs) …")

        for start in range(0, args.count, args.batch):
            end   = min(start + args.batch, args.count)
            batch = [gen_fn(start + i + 1) for i in range(end - start)]
            ok, err = bulk_index(client, batch, index_name)
            total_ok  += ok
            total_err += err
            if (end // args.batch) % 4 == 0 or end == args.count:
                print(f"    [{end:>7,}/{args.count:,}]  +{ok}  errors={err}")

        client._client.indices.refresh(index=index_name)
        print(f"✓  {index_name}: {total_ok:,} indexed, {total_err} errors.\n")

    print("All done.")


if __name__ == "__main__":
    main()
