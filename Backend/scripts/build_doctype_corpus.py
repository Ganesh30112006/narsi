"""Synthetic corpus for the document-type classifier: pages of each Indian ID/document type, rendered with varied
layouts, degraded like bad phone photos, and read with the production OCR. Writes one OCR text per page.

    python scripts/build_doctype_corpus.py --per-class 140 --seed 11 --out dataset/doctype/train.jsonl

Wording follows the headings and field labels printed on the real documents. All values are random. Layouts drop,
reorder and rewrap lines, since real photos are cropped and OCR loses lines.
"""

from __future__ import annotations

import argparse
import json
import random
import sys
import tempfile
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

FIRST = ["Rohan", "Meera", "Arjun", "Kavya", "Imran", "Pooja", "Suresh", "Anita", "Vikram", "Neha", "Karthik", "Sana"]
LAST = ["Kumar", "Verma", "Das", "Iyer", "Pillai", "Gupta", "Singh", "Menon", "Bose", "Reddy", "Sharma", "Nair"]
CITIES = ["Pune", "Hyderabad", "Kolkata", "Chennai", "Lucknow", "Jaipur", "Kochi", "Ongole", "Nagpur", "Patna"]
STATES = ["Maharashtra", "Telangana", "West Bengal", "Tamil Nadu", "Uttar Pradesh", "Rajasthan", "Kerala", "Bihar"]


def r(rng: random.Random, n: int) -> str:
    return "".join(str(rng.randint(0, 9)) for _ in range(n))


def L(rng: random.Random, n: int) -> str:
    return "".join(rng.choice("ABCDEFGHJKLMNPRSTUVWXYZ") for _ in range(n))


def person(rng: random.Random) -> str:
    return f"{rng.choice(FIRST)} {rng.choice(LAST)}"


def dob(rng: random.Random) -> str:
    return f"{rng.randint(1, 28):02d}/{rng.randint(1, 12):02d}/{rng.randint(1955, 2003)}"


def aadhaar(rng: random.Random) -> list[list[str]]:
    number = f"{rng.randint(2, 9)}{r(rng, 3)} {r(rng, 4)} {r(rng, 4)}"
    vid = "VID : " + " ".join(r(rng, 4) for _ in range(4))
    return [
        rng.choice(
            [["Government of India"], ["Unique Identification Authority of India"], ["Government of India", "Aadhaar"]]
        ),
        [rng.choice(["Aadhaar", "AADHAAR", "Aadhaar - Aam Aadmi Ka Adhikar"])],
        [f"{rng.choice(['DOB', 'Date of Birth'])}: {dob(rng)}", rng.choice(["Male", "Female", "MALE", "FEMALE"])],
        [person(rng)],
        [number],
        [rng.choice(["Your Aadhaar No. :", "Your Aadhaar No.:", vid])],
        ["Enrolment No.: " + f"{r(rng, 4)}/{r(rng, 5)}/{r(rng, 5)}"],
        ["Aadhaar is a proof of identity, not of citizenship", "To establish identity, authenticate online"],
        ["help@uidai.gov.in  www.uidai.gov.in  1947"],
        [f"Address: C/O {person(rng)}, {r(rng, 2)}, {rng.choice(CITIES)}, {rng.choice(STATES)} - {r(rng, 6)}"],
    ]


def pan(rng: random.Random) -> list[list[str]]:
    number = L(rng, 5) + r(rng, 4) + L(rng, 1)
    return [
        ["INCOME TAX DEPARTMENT", "GOVT. OF INDIA"],
        [rng.choice(["Permanent Account Number Card", "Permanent Account Number"])],
        [number],
        ["Name", person(rng).upper()],
        ["Father's Name", person(rng).upper()],
        ["Date of Birth", dob(rng)],
        ["Signature"],
        ["Permanent Account Number"],
    ]


def passport(rng: random.Random) -> list[list[str]]:
    sur, giv = rng.choice(LAST).upper(), rng.choice(FIRST).upper()
    no = L(rng, 1) + r(rng, 7)
    mrz1 = f"P<IND{sur}<<{giv}".ljust(44, "<")
    mrz2 = f"{no}<{r(rng, 1)}IND{r(rng, 6)}{r(rng, 1)}M{r(rng, 6)}{r(rng, 1)}" + "<" * 14 + "<0"
    return [
        ["REPUBLIC OF INDIA"],
        ["Type P", "Country Code IND", f"Passport No. {no}"],
        ["Surname", sur, "Given Name(s)", giv],
        ["Nationality INDIAN", "Sex M", f"Date of Birth {dob(rng)}"],
        [
            f"Place of Birth {rng.choice(CITIES).upper()}, {rng.choice(STATES).upper()}",
            "Place of Issue " + rng.choice(CITIES).upper(),
        ],
        [f"Date of Issue {dob(rng)}", f"Date of Expiry {dob(rng)}"],
        [mrz1],
        [mrz2],
    ]


def voter(rng: random.Random) -> list[list[str]]:
    return [
        ["ELECTION COMMISSION OF INDIA"],
        [rng.choice(["ELECTOR PHOTO IDENTITY CARD", "Elector's Photo Identity Card", "Identity Card"])],
        [L(rng, 3) + r(rng, 7)],
        ["Elector's Name", person(rng)],
        ["Father's Name", person(rng)],
        [rng.choice(["Sex : Male", "Sex : Female"]), f"Date of Birth / Age : {dob(rng)}"],
        ["Address", f"{r(rng, 2)}, {rng.choice(CITIES)}, {rng.choice(STATES)}"],
        ["Electoral Registration Officer", "Assembly Constituency No. and Name"],
    ]


def licence(rng: random.Random) -> list[list[str]]:
    st = rng.choice(["MH", "KA", "DL", "TN", "TS", "UP"])
    return [
        [
            rng.choice(["Union of India", "DRIVING LICENCE", "INDIAN UNION DRIVING LICENCE"]),
            rng.choice(["Driving Licence", "Transport Department"]),
        ],
        [f"DL No. {st}{r(rng, 2)} {rng.randint(2008, 2022)}{r(rng, 7)}"],
        ["Name", person(rng)],
        ["S/D/W of", person(rng)],
        [f"Date of Birth {dob(rng)}", "Blood Group O+"],
        [f"Date of First Issue {dob(rng)}", f"Valid Till {dob(rng)}", "(NT) Non-Transport", "(T) Transport"],
        [rng.choice(["Class of Vehicles COV", "COV : MCWG LMV"]), "Issuing Authority RTO " + rng.choice(CITIES)],
        ["Signature of Holder", "Address " + f"{r(rng, 2)}, {rng.choice(CITIES)}"],
    ]


def certificate(rng: random.Random) -> list[list[str]]:
    subjects = [
        f"{s} {rng.randint(35, 99)} {rng.choice('ABC')}" for s in ("Mathematics", "Science", "English", "Hindi")
    ]
    return [
        [
            rng.choice(
                [
                    "BOARD OF SECONDARY EDUCATION",
                    "BOARD OF INTERMEDIATE EDUCATION",
                    "CENTRAL BOARD OF SECONDARY EDUCATION",
                ]
            ),
            rng.choice(["SECONDARY SCHOOL CERTIFICATE", "MARKS MEMORANDUM", "PASS CERTIFICATE"]),
        ],
        [f"Roll No. {r(rng, 10)}", f"Hall Ticket No {r(rng, 8)}"],
        ["Certified that", person(rng).upper()],
        [f"Father's Name {person(rng).upper()}", f"Mother's Name {person(rng).upper()}"],
        [f"Date of Birth {dob(rng)}", "has passed the Examination held in March 2021"],
        ["Subject Marks Grade", *subjects],
        ["Marks of Identification", f"A mole on the {rng.choice(['left hand', 'neck', 'right knee'])}"],
        ["Controller of Examinations", "Result : PASS"],
    ]


def other(rng: random.Random) -> list[list[str]]:
    kind = rng.randrange(5)
    if kind == 0:
        rows = [f"Item{n} {rng.randint(1, 20)} {rng.randint(10, 900)}" for n in range(4)]
        return [
            ["TAX INVOICE"],
            [f"Invoice No. INV{r(rng, 8)}", f"Date {dob(rng)}"],
            ["Bill To", rng.choice(CITIES) + " Traders Pvt Ltd"],
            ["Item Qty Rate Amount", *rows],
            [f"GSTIN 27{L(rng, 5)}{r(rng, 4)}{L(rng, 1)}1Z5", f"Total Rs. {rng.randint(500, 90000)}"],
        ]
    if kind == 1:
        return [
            ["Dear Sir/Madam,"],
            [f"This is to confirm the meeting on {dob(rng)} regarding the quarterly procurement summary."],
            ["Please find the attached report and let us know if any changes are required."],
            ["Regards", person(rng)],
        ]
    if kind == 2:
        return [
            ["Employee application form"],
            [f"Applicant name: {person(rng)}", f"Mobile: {r(rng, 10)}"],
            [f"Email: {rng.choice(FIRST).lower()}@example.in"],
            ["Department", rng.choice(["Finance", "Legal", "Procurement"])],
            ["Signature", "Date"],
        ]
    if kind == 3:
        rows = [f"{dob(rng)} UPI/{r(rng, 6)} {rng.randint(10, 9000)}" for _ in range(4)]
        return [
            ["BANK STATEMENT"],
            [f"Account No. {r(rng, 12)}", "IFSC " + L(rng, 4) + "0" + r(rng, 6)],
            ["Date Narration Debit Credit Balance", *rows],
        ]
    return [
        ["Welcome to the Annual Conference"],
        ["Agenda", "Registration 9:00", "Keynote 10:00", "Lunch 13:00"],
        ["Venue " + rng.choice(CITIES) + " Convention Centre"],
        ["Contact us for sponsorship opportunities"],
    ]


GENERATORS = {
    "AADHAAR": aadhaar,
    "PAN": pan,
    "PASSPORT": passport,
    "VOTER_ID": voter,
    "DRIVING_LICENSE": licence,
    "CERTIFICATE": certificate,
    "OTHER": other,
}


def render(blocks: list[list[str]], rng: random.Random) -> Image.Image:
    size = rng.choice([22, 26, 30, 34])
    font = ImageFont.load_default(size=size)
    lines = [text for block in blocks for text in block if rng.random() > 0.12]  # lines lost to crop/OCR
    if rng.random() < 0.3:
        rng.shuffle(lines)  # a different layout order
    width = rng.choice([1200, 1500, 1700])
    spacing = int(size * rng.uniform(1.4, 1.9))
    image = Image.new("RGB", (width, max(500, 100 + spacing * (len(lines) + 1))), (rng.randint(235, 255),) * 3)
    draw = ImageDraw.Draw(image)
    y = 50
    for line in lines:
        draw.text((rng.randint(40, 120), y), line, fill=(rng.randint(0, 50),) * 3, font=font)
        y += spacing
    return image


def make(job: tuple[str, int, int]) -> dict[str, object]:
    from degrade import PRESETS, degrade

    from app.core.enums import FileType
    from app.processing.dispatcher import extract_document
    from app.processing.limits import ProcessingLimits

    label, seed, severity_cap = job
    rng = random.Random(seed)
    image = render(GENERATORS[label](rng), rng)
    preset = rng.choice(list(PRESETS))
    severity = rng.uniform(0, severity_cap / 100)
    if severity > 0.05:
        image = degrade(image, preset, severity, seed)
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "page.png"
        image.save(path)
        document = extract_document(path, FileType.PNG, limits=ProcessingLimits(), ocr_enabled=True)
    return {"label": label, "preset": preset, "severity": round(severity, 2), "text": document.pages[0].text}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--per-class", type=int, default=140)
    parser.add_argument("--seed", type=int, default=11)
    parser.add_argument("--severity-cap", type=int, default=65, help="max degradation severity, percent")
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    jobs = [
        (label, args.seed * 100_000 + index * 997 + k, args.severity_cap)
        for index, label in enumerate(GENERATORS)
        for k in range(args.per_class)
    ]
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with ProcessPoolExecutor(args.workers) as pool, args.out.open("w", encoding="utf-8") as handle:
        for done, row in enumerate(pool.map(make, jobs, chunksize=4), 1):
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
            if done % 100 == 0:
                print(done, "/", len(jobs), flush=True)


if __name__ == "__main__":
    main()
