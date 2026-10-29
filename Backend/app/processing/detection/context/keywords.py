"""Context vocabularies. Positive labels raise confidence; negative labels indicate a different identifier."""

from __future__ import annotations

import unicodedata

from app.core.enums import GOVERNMENT_ID_TYPES, PIIType

POSITIVE: dict[PIIType, tuple[str, ...]] = {
    PIIType.AADHAAR: (
        "aadhaar",
        "aadhar",
        "adhaar",
        "aadhaar no",
        "aadhaar number",
        "uid",
        "uid no",
        "uidai",
        "unique identification",
        "आधार",
    ),
    PIIType.AADHAAR_VID: ("vid", "vid no", "virtual id", "virtual id number", "aadhaar vid", "aadhaar virtual id"),
    PIIType.AADHAAR_ENROLMENT: (
        "enrolment no",
        "enrollment no",
        "enrolment number",
        "enrolment id",
        "eid",
    ),
    PIIType.PAN: ("pan", "pan no", "pan number", "pan card", "permanent account number", "permanent account no"),
    PIIType.PASSPORT: ("passport", "passport no", "passport number", "travel document"),
    PIIType.VOTER_ID: (
        "voter id",
        "voter",
        "voter card",
        "epic",
        "epic no",
        "electoral",
        "elector",
        "election card",
        "election id",
    ),
    PIIType.DRIVING_LICENSE: (
        "driving licence",
        "driving license",
        "driving licence no",
        "driver's licence",
        "driver license",
        "dl no",
        "dl number",
        "licence no",
        "license no",
        "licence number",
        "license number",
        "dl",
    ),
    PIIType.PHONE: (
        "phone",
        "phone no",
        "mobile",
        "mobile no",
        "mob",
        "contact",
        "contact no",
        "contact number",
        "tel",
        "telephone",
        "cell",
        "whatsapp",
        "ph",
    ),
    PIIType.EMAIL: ("email", "e-mail", "email id", "email address", "mail"),
    PIIType.NAME: (
        "name",
        "full name",
        "applicant name",
        "applicant",
        "employee name",
        "customer name",
        "candidate name",
        "holder name",
        "card holder",
        "father's name",
        "fathers name",
        "mother's name",
        "spouse name",
        "guardian name",
        "nominee",
        "beneficiary",
        # Relation prefixes on Indian ID documents: care of, son/daughter/wife of.
        "c/o",
        "s/o",
        "d/o",
        "w/o",
    ),
    PIIType.ADDRESS: (
        "address",
        "residential address",
        "permanent address",
        "correspondence address",
        "current address",
        "postal address",
        "home address",
        "residence",
        "addr",
    ),
    PIIType.DATE_OF_BIRTH: ("date of birth", "dob", "d.o.b", "d o b", "birth date", "birthdate", "born on", "born"),
}

# Hindi and Telugu labels as printed on bilingual ID documents ("जन्म तिथि/DOB", "పుట్టిన తేదీ"). Written without
# zero-width joiners, which normalization removes from the page text too.
INDIC_POSITIVE: dict[PIIType, tuple[str, ...]] = {
    PIIType.AADHAAR: ("आधार संख्या", "आधार क्रमांक", "ఆధార్", "ఆధార్ సంఖ్య"),
    PIIType.AADHAAR_VID: ("वीआईडी", "आभासी पहचान"),
    PIIType.AADHAAR_ENROLMENT: ("नामांकन क्रम", "नामांकन संख्या", "నమోదు సంఖ్య"),
    PIIType.PAN: ("स्थायी लेखा संख्या", "శాశ్వత ఖాతా సంఖ్య"),
    PIIType.PASSPORT: ("पासपोर्ट", "पासपोर्ट संख्या", "పాస్పోర్ట్"),
    PIIType.VOTER_ID: ("मतदाता पहचान पत्र", "निर्वाचक", "मतदाता", "ఓటరు", "ఓటరు గుర్తింపు"),
    PIIType.DRIVING_LICENSE: ("ड्राइविंग लाइसेंस", "చోదక అనుమతి", "డ్రైవింగ్ లైసెన్స్"),
    PIIType.PHONE: ("मोबाइल", "फोन", "दूरभाष", "మొబైల్", "ఫోన్"),
    PIIType.EMAIL: ("ईमेल", "ఇమెయిల్"),
    PIIType.NAME: ("नाम", "पिता का नाम", "माता का नाम", "पति का नाम", "పేరు", "తండ్రి పేరు", "తల్లి పేరు"),
    PIIType.ADDRESS: ("पता", "చిరునామా"),
    PIIType.DATE_OF_BIRTH: ("जन्म तिथि", "जन्मतिथि", "जन्म की तारीख", "పుట్టిన తేదీ", "జనన తేదీ"),
}

# Labels that apply to any government ID but are weaker than a type-specific label.
GENERIC_ID = (
    "government id",
    "govt id",
    "id number",
    "id no",
    "identification number",
    "identity number",
    "identity card",
    "id proof",
    "kyc",
    "document number",
)

# Labels that indicate a *different* kind of identifier.
NEGATIVE_COMMON = (
    "invoice",
    "invoice no",
    "invoice number",
    "inv no",
    "order",
    "order id",
    "order no",
    "transaction",
    "transaction id",
    "txn",
    "txn id",
    "reference",
    "ref no",
    "ref",
    "account no",
    "account number",
    "a/c",
    "acct",
    "employee id",
    "employee no",
    "employee number",
    "emp id",
    "emp no",
    "staff id",
    "application no",
    "application number",
    "application id",
    "ticket",
    "serial",
    "serial no",
    "s/n",
    "tracking",
    "awb",
    "policy no",
    "policy number",
    "claim no",
    "receipt",
    "voucher",
    "batch",
    "lot no",
    "sku",
    "product code",
    "model no",
    "part no",
    "customer id",
    "member id",
    "roll no",
    "registration no",
    "gstin",
    "ifsc",
    "otp",
    "amount",
    "pin code",
    "pincode",
    "postal code",
    "zip",
    "request id",
    "case no",
    "file no",
)

NEGATIVE_EXTRA: dict[PIIType, tuple[str, ...]] = {
    PIIType.DATE_OF_BIRTH: (
        "issue date",
        "date of issue",
        "issued on",
        "expiry",
        "expiry date",
        "valid till",
        "valid upto",
        "valid until",
        "due date",
        "invoice date",
        "date of joining",
        "joining date",
        "order date",
        "payment date",
        "date",
        "dated",
    ),
    PIIType.NAME: (
        "company name",
        "bank name",
        "branch name",
        "file name",
        "filename",
        "product name",
        "organisation name",
        "organization name",
        "org name",
        "user name",
        "username",
        "domain name",
        "host name",
        "hostname",
        "school name",
        "college name",
        "vendor name",
        "department name",
    ),
    PIIType.PHONE: ("fax",),
    PIIType.AADHAAR_VID: ("card no", "card number", "credit card", "debit card"),
}

# Address-part labels. A capitalised value right after one of these is a place, not a person
# ("State: Andhra Pradesh"). Matched as whole words by the context analyzer only.
LOCATION_LABELS = (
    "state",
    "district",
    "sub district",
    "city",
    "town",
    "village",
    "vtc",
    "po",
    "post office",
    "taluk",
    "taluka",
    "tehsil",
    "mandal",
    "country",
    "place",
    "locality",
    "landmark",
)


def positive_labels(pii_type: PIIType) -> tuple[tuple[str, float], ...]:
    labels = [(label, 1.0) for label in POSITIVE.get(pii_type, ())]
    labels.extend((unicodedata.normalize("NFKC", label), 1.0) for label in INDIC_POSITIVE.get(pii_type, ()))
    if pii_type in GOVERNMENT_ID_TYPES:
        labels.extend((label, 0.6) for label in GENERIC_ID)
    return tuple(labels)


def negative_labels(pii_type: PIIType) -> tuple[str, ...]:
    extra = NEGATIVE_EXTRA.get(pii_type, ())
    if pii_type is PIIType.NAME:
        return extra + LOCATION_LABELS
    if pii_type in (PIIType.ADDRESS, PIIType.EMAIL):
        return extra
    if pii_type is PIIType.DATE_OF_BIRTH:
        return extra
    return NEGATIVE_COMMON + extra
