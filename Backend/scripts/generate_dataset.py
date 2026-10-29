"""Generates a synthetic, labelled test corpus. No real personal data is used.

All identifiers are random values constructed to match documented structures (e.g. Aadhaar-format
numbers carry a valid Verhoeff check digit). Names and addresses are drawn from generic word lists.

    python scripts/generate_dataset.py --split dev --seed 7
    python scripts/generate_dataset.py --split test --seed 2026
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import io
import json
import math
import random
import shutil
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from xml.sax.saxutils import escape

import cv2
import docx
import pymupdf
from openpyxl import Workbook
from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.processing.detection.validators.identifiers import icao_check_digit  # noqa: E402
from app.processing.detection.validators.verhoeff import verhoeff_check_digit  # noqa: E402

FIRST = [
    "Rohan",
    "Meera",
    "Arjun",
    "Kavya",
    "Imran",
    "Sneha",
    "Rahul",
    "Farah",
    "Aditya",
    "Lakshmi",
    "Devika",
    "Sanjay",
    "Priya",
    "Vikram",
    "Ananya",
    "Karthik",
    "Neha",
    "Suresh",
    "Pooja",
    "Harish",
    "Divya",
    "Manoj",
]
LAST = [
    "Kumar",
    "Iyer",
    "Sharma",
    "Nair",
    "Khan",
    "Reddy",
    "Patel",
    "Das",
    "Joshi",
    "Menon",
    "Gupta",
    "Bose",
    "Verma",
    "Pillai",
    "Rao",
    "Mehta",
    "Chatterjee",
    "Singh",
    "Kulkarni",
    "Banerjee",
]
STREETS = [
    "2nd Cross Road",
    "MG Road",
    "Park Street",
    "Linking Road",
    "Anna Salai",
    "Station Road",
    "Temple Street",
    "Lake View Lane",
    "Nehru Nagar Main Road",
    "Gandhi Marg",
]
AREAS = ["Indiranagar", "Bandra West", "Salt Lake", "T Nagar", "Sector 21", "Kothrud", "Jayanagar", "Aundh"]
CITIES = [
    ("Bengaluru", "560038"),
    ("Mumbai", "400050"),
    ("Kolkata", "700091"),
    ("Chennai", "600017"),
    ("Noida", "201301"),
    ("Pune", "411038"),
    ("Hyderabad", "500034"),
    ("Jaipur", "302017"),
]
STATE_OF = {
    "Bengaluru": "Karnataka",
    "Mumbai": "Maharashtra",
    "Kolkata": "West Bengal",
    "Chennai": "Tamil Nadu",
    "Noida": "Uttar Pradesh",
    "Pune": "Maharashtra",
    "Hyderabad": "Telangana",
    "Jaipur": "Rajasthan",
}
STATES = ["MH", "KA", "DL", "TN", "WB", "GJ", "RJ", "TS", "KL", "UP"]
DOMAINS = ["example.in", "example.com", "mail.example.org", "test.example.net"]
COMPANIES = ["Sunrise Traders Pvt Ltd", "Bluewave Logistics", "Greenfield Agro Industries", "Metro Fabrications"]


@dataclass
class Label:
    pii_type: str
    value: str
    page: int = 1


@dataclass
class Distractor:
    kind: str
    value: str


@dataclass
class Sample:
    file: str
    category: str
    labels: list[Label] = field(default_factory=list)
    distractors: list[Distractor] = field(default_factory=list)


class Values:
    def __init__(self, rng: random.Random) -> None:
        self.rng = rng

    def digits(self, n: int) -> str:
        return "".join(str(self.rng.randint(0, 9)) for _ in range(n))

    def letters(self, n: int) -> str:
        return "".join(self.rng.choice("ABCDEFGHJKLMNPRSTUVWXYZ") for _ in range(n))

    def aadhaar(self) -> str:
        base = str(self.rng.randint(2, 9)) + self.digits(10)
        return base + verhoeff_check_digit(base)

    def vid(self) -> str:
        base = str(self.rng.randint(1, 9)) + self.digits(14)
        return base + verhoeff_check_digit(base)

    def invalid_aadhaar(self) -> str:
        value = self.aadhaar()
        return value[:-1] + str((int(value[-1]) + self.rng.randint(1, 9)) % 10)

    def pan(self) -> str:
        return (
            self.letters(3)
            + self.rng.choice("PCHFATBLJG")
            + self.letters(1)
            + f"{self.rng.randint(1, 9999):04d}"
            + self.letters(1)
        )

    def passport(self) -> str:
        return (
            self.rng.choice("ABCDEFGHJKLMNPRSTUVW")
            + str(self.rng.randint(1, 9))
            + self.digits(5)
            + str(self.rng.randint(1, 9))
        )

    def voter(self) -> str:
        return self.letters(3) + f"{self.rng.randint(1, 9999999):07d}"

    def dl(self) -> str:
        state, rto = self.rng.choice(STATES), self.rng.randint(1, 60)
        return f"{state}{rto:02d}{self.rng.randint(2005, 2023)}{self.rng.randint(1, 9999999):07d}"

    def phone(self) -> str:
        return str(self.rng.randint(6, 9)) + self.digits(9)

    def name(self) -> str:
        return f"{self.rng.choice(FIRST)} {self.rng.choice(LAST)}"

    def email(self, name: str) -> str:
        first, last = name.lower().split()
        return f"{first}.{last}{self.rng.randint(1, 99)}@{self.rng.choice(DOMAINS)}"

    def address(self) -> str:
        city, pin = self.rng.choice(CITIES)
        return f"{self.rng.randint(3, 220)}, {self.rng.choice(STREETS)}, {self.rng.choice(AREAS)}, {city} {pin}"

    def dob(self) -> dt.date:
        return dt.date(self.rng.randint(1955, 2004), self.rng.randint(1, 12), self.rng.randint(1, 28))


def spaced(value: str, groups: tuple[int, ...], sep: str) -> str:
    out, cursor = [], 0
    for size in groups:
        out.append(value[cursor : cursor + size])
        cursor += size
    return sep.join(out)


def fmt_phone(value: str, rng: random.Random) -> str:
    return rng.choice([value, f"+91 {value[:5]} {value[5:]}", f"+91-{value}", f"0{value}", f"{value[:5]}-{value[5:]}"])


# --------------------------------------------------------------------------- content builders


def record(v: Values, sample: Sample, *, style: str = "plain", page: int = 1) -> list[str]:
    """A personal record block. style: plain | spaced | hyphen | mixedcase | split."""
    rng = v.rng
    name, aadhaar, pan, phone = v.name(), v.aadhaar(), v.pan(), v.phone()
    email, address, dob = v.email(name), v.address(), v.dob()
    aadhaar_text = {
        "plain": aadhaar,
        "spaced": spaced(aadhaar, (4, 4, 4), " "),
        "hyphen": spaced(aadhaar, (4, 4, 4), "-"),
        "mixedcase": spaced(aadhaar, (4, 4, 4), " "),
        "split": spaced(aadhaar, (4, 4), " ") + "\n" + aadhaar[8:],
    }[style]
    pan_text = pan.lower() if style == "mixedcase" else pan
    lines = [
        f"Applicant name: {name}",
        f"Aadhaar No: {aadhaar_text}",
        f"PAN: {pan_text}",
        f"Mobile: {fmt_phone(phone, rng)}",
        f"Email: {email}",
        f"Date of Birth: {dob.strftime(rng.choice(['%d/%m/%Y', '%d-%m-%Y', '%d %B %Y']))}",
        f"Residential address: {address}",
    ]
    sample.labels += [
        Label("NAME", name, page),
        Label("AADHAAR", aadhaar, page),
        Label("PAN", pan, page),
        Label("PHONE", phone, page),
        Label("EMAIL", email, page),
        Label("DATE_OF_BIRTH", dob.isoformat(), page),
        Label("ADDRESS", address, page),
    ]
    if rng.random() < 0.6:
        passport = v.passport()
        lines.append(f"Passport No: {passport}")
        sample.labels.append(Label("PASSPORT", passport, page))
    if rng.random() < 0.5:
        dl = v.dl()
        lines.append(f"Driving Licence No: {spaced(dl, (4, 11), ' ') if rng.random() < 0.5 else dl}")
        sample.labels.append(Label("DRIVING_LICENSE", dl, page))
    if rng.random() < 0.5:
        voter = v.voter()
        lines.append(f"Voter ID (EPIC): {voter}")
        sample.labels.append(Label("VOTER_ID", voter, page))
    return lines


def distractors(v: Values, sample: Sample, count: int) -> list[str]:
    rng = v.rng
    makers = [
        (
            "invoice",
            lambda: (lambda x: (f"Invoice Number: {x}", x))(v.aadhaar() if rng.random() < 0.5 else v.digits(12)),
        ),
        ("transaction", lambda: (lambda x: (f"Transaction ID: {x}", x))(v.digits(12))),
        ("account", lambda: (lambda x: (f"Account No: {x}", x))(v.phone())),
        ("employee", lambda: (lambda x: (f"Employee ID: {x}", x))(v.letters(1) + v.digits(7))),
        ("order", lambda: (lambda x: (f"Order ID: {x}", x))(v.letters(3) + v.digits(7))),
        ("postal", lambda: (lambda x: (f"PIN code: {x}", x))(rng.choice(CITIES)[1])),
        (
            "issue_date",
            lambda: (lambda d: (f"Issue date: {d.strftime('%d/%m/%Y')}", d.isoformat()))(
                dt.date(rng.randint(2015, 2025), rng.randint(1, 12), rng.randint(1, 28))
            ),
        ),
        ("company", lambda: (lambda c: (f"Company name: {c}", c))(rng.choice(COMPANIES))),
        ("reference", lambda: (lambda x: (f"Ref no: {x}", x))(v.letters(5) + v.digits(4) + v.letters(1))),
    ]
    lines = []
    for kind, make in rng.sample(makers, k=min(count, len(makers))):
        line, value = make()
        lines.append(line)
        sample.distractors.append(Distractor(kind, value))
    return lines


def aadhaar_letter(v: Values, sample: Sample) -> list[str]:
    """Layout of an e-Aadhaar letter: address block with part labels, number and VID printed twice, holder name
    on both halves. In half of the letters the "DOB:" label is missing, as happens when OCR garbles the
    bilingual label; the date is then only identifiable by the gender printed under it."""
    rng = v.rng
    name, relative = v.name(), v.name()
    aadhaar, vid, dob = v.aadhaar(), v.vid(), v.dob()
    city, pin = rng.choice(CITIES)
    area = rng.choice(AREAS)
    address = [
        f"C/O {relative},",
        f"{rng.randint(1, 220)}, {rng.choice(STREETS)},",
        f"{area},",
        f"VTC: {city}, PO: {area},",
        f"District: {city},",
        f"State: {STATE_OF[city]},",
        f"PIN Code: {pin}",
    ]
    number, virtual = spaced(aadhaar, (4, 4, 4), " "), spaced(vid, (4, 4, 4, 4), " ")
    dob_text = dob.strftime("%d/%m/%Y")
    enrolment = f"{v.digits(4)}/{v.digits(5)}/{v.digits(5)}"  # drawn here, where the list used to draw it
    lines = [
        "Unique Identification Authority of India",
        "Government of India",
        f"Enrolment No.: {enrolment}",
        "To",
        name,
        *address,
        "Your Aadhaar No. :",
        number,
        f"VID : {virtual}",
        "Aadhaar is proof of identity, not of citizenship or date of birth.",
        name,
        f"DOB: {dob_text}" if rng.random() < 0.5 else dob_text,
        rng.choice(["MALE", "FEMALE"]),
        number,
        f"VID : {virtual}",
        "help@uidai.gov.in | www.uidai.gov.in",
    ]
    sample.labels += [
        Label("NAME", name),
        Label("NAME", name),
        Label("NAME", relative),
        Label("ADDRESS", " ".join(address)),
        Label("AADHAAR", aadhaar),
        Label("AADHAAR", aadhaar),
        Label("AADHAAR_VID", vid),
        Label("AADHAAR_VID", vid),
        Label("DATE_OF_BIRTH", dob.isoformat()),
        Label("AADHAAR_ENROLMENT", enrolment.replace("/", "")),
    ]
    sample.distractors.append(Distractor("issuer_email", "help@uidai.gov.in"))
    return lines


def passport_page(v: Values, sample: Sample) -> list[str]:
    """Passport data page: labels above values, "Date of Birth / Sex" on one line, and a TD3 machine-readable zone
    with valid ICAO check digits. Issue and expiry dates are distractors."""
    rng = v.rng
    surname, given = rng.choice(LAST).upper(), rng.choice(FIRST).upper()
    number = rng.choice("ABCDEFGHJKLMNPRSTUVWXZ") + str(rng.randint(1, 9)) + v.digits(5) + str(rng.randint(1, 9))
    dob = v.dob()
    issue = dt.date(rng.randint(2016, 2024), rng.randint(1, 12), rng.randint(1, 28))
    expiry = issue.replace(year=issue.year + 10) - dt.timedelta(days=1)
    sex = rng.choice("MF")
    doc, yymmdd, expires = number.ljust(9, "<"), dob.strftime("%y%m%d"), expiry.strftime("%y%m%d")
    line1 = f"P<IND{surname}<<{given}".ljust(44, "<")
    line2 = (
        f"{doc}{icao_check_digit(doc)}IND{yymmdd}{icao_check_digit(yymmdd)}{sex}{expires}{icao_check_digit(expires)}"
        + "<" * 14
        + "00"
    )
    city = rng.choice(CITIES)[0].upper()
    lines = [
        "REPUBLIC OF INDIA",
        f"Type P  Country Code IND  Passport No. {number}",
        "Surname",
        surname,
        "Given Name(s)",
        given,
        "Date of Birth  Sex",
        f"{dob.strftime('%d/%m/%Y')} {sex}",
        "Place of Birth",
        city,
        "Date of Issue",
        issue.strftime("%d/%m/%Y"),
        "Date of Expiry",
        expiry.strftime("%d/%m/%Y"),
        line1,
        line2,
    ]
    sample.labels += [
        Label("PASSPORT", number),
        Label("PASSPORT", number),
        Label("NAME", surname),
        Label("NAME", given),
        Label("NAME", f"{surname} {given}"),
        Label("PLACE_OF_BIRTH", city),
        Label("DATE_OF_BIRTH", dob.isoformat()),
        Label("DATE_OF_BIRTH", dob.isoformat()),
    ]
    sample.distractors += [
        Distractor("issue_date", issue.isoformat()),
        Distractor("expiry_date", expiry.isoformat()),
    ]
    return lines


def school_certificate(v: Values, sample: Sample) -> list[str]:
    """Board certificate: names in capitals with their labels on the line above."""
    rng = v.rng
    family = rng.choice(LAST).upper()
    candidate, father, mother = (f"{family} {rng.choice(FIRST).upper()}" for _ in range(3))
    dob = v.dob()
    school = f"SRI {rng.choice(LAST).upper()} HIGH SCHOOL"
    roll = v.digits(10)
    lines = [
        "BOARD OF SECONDARY EDUCATION",
        "SECONDARY SCHOOL CERTIFICATE",
        "Certified that",
        candidate,
        "Father's Name",
        father,
        "Mother's Name",
        mother,
        "Roll No.",
        roll,
        "Date of Birth",
        dob.strftime("%d/%m/%Y"),
        "School Name",
        school,
        "has Registered and Passed SSC Examination held in MARCH 2021 in FIRST Division.",
    ]
    sample.labels += [
        Label("NAME", candidate),
        Label("NAME", father),
        Label("NAME", mother),
        Label("DATE_OF_BIRTH", dob.isoformat()),
    ]
    sample.distractors.append(Distractor("school", school))
    sample.labels.append(Label("ROLL_NUMBER", roll))
    # Identification marks, listed around their label as on board certificates. Drawn last so the documents
    # generated before 1.3.0 keep their content.
    marks = rng.sample(["A MOLE ON THE LEFT HAND", "A SCAR ON THE RIGHT KNEE", "A MOLE ON THE NECK"], k=2)
    lines[-1:-1] = [f"1) {marks[0]}", "Marks of Identification:", f"2) {marks[1]}"]
    sample.labels += [Label("IDENTIFICATION_MARK", mark) for mark in marks]
    return lines


def prose_line(v: Values, sample: Sample) -> str:
    name = v.name()
    sample.labels.append(Label("NAME", name))
    return f"The request was reviewed by {name} and forwarded to the records office."


# --------------------------------------------------------------------------- writers


def write_txt(path: Path, lines: list[str]) -> None:
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_pdf(path: Path, pages: list[list[str]]) -> None:
    document = pymupdf.open()
    for lines in pages:
        page = document.new_page()
        y = 72
        for line in lines:
            for part in line.split("\n"):
                page.insert_text((60, y), part, fontsize=11)
                y += 20
    document.save(str(path))
    document.close()


def text_image(lines: list[str], *, noisy: bool, rng: random.Random) -> Image.Image:
    font = ImageFont.load_default(size=30)
    height = 120 + 52 * sum(line.count("\n") + 1 for line in lines)
    image = Image.new("L", (1700, max(height, 400)), 255)
    draw = ImageDraw.Draw(image)
    y = 60
    for line in lines:
        for part in line.split("\n"):
            draw.text((70, y), part, fill=0, font=font)
            y += 52
    if noisy:
        image = image.rotate(rng.uniform(-1.2, 1.2), expand=False, fillcolor=255)
        image = image.filter(ImageFilter.GaussianBlur(0.8))
        pixels = image.load()
        for _ in range(image.width * image.height // 400):
            pixels[rng.randrange(image.width), rng.randrange(image.height)] = rng.choice((0, 160, 255))
    return image.convert("RGB")


def write_scanned_pdf(path: Path, lines: list[str], rng: random.Random) -> None:
    image = text_image(lines, noisy=False, rng=rng)
    tmp = path.with_suffix(".png")
    image.save(tmp)
    document = pymupdf.open()
    page = document.new_page(width=612, height=612 * image.height / image.width)
    page.insert_image(page.rect, filename=str(tmp))
    document.save(str(path))
    document.close()
    tmp.unlink()


def write_docx(path: Path, lines: list[str], table: list[list[str]] | None = None) -> None:
    document = docx.Document()
    for line in lines:
        document.add_paragraph(line)
    if table:
        grid = document.add_table(rows=len(table), cols=len(table[0]))
        for r, row in enumerate(table):
            for c, value in enumerate(row):
                grid.cell(r, c).text = value
    document.save(str(path))


def qr_code(payload: str, size: int) -> Image.Image:
    """A real QR code (OpenCV's encoder), scaled with nearest-neighbour so its modules stay square."""
    matrix = cv2.QRCodeEncoder.create().encode(payload)
    return Image.fromarray(matrix).convert("L").resize((size, size), Image.Resampling.NEAREST)


def signature_strokes(rng: random.Random, width: int, height: int) -> Image.Image:
    """Handwriting-like ink: a looping baseline stroke and a slanted flourish (no real signature is used)."""
    image = Image.new("L", (width, height), 255)
    draw = ImageDraw.Draw(image)
    stroke = max(2, height // 22)
    frequency, phase = rng.uniform(9, 15), rng.uniform(0, math.pi)
    points = []
    for step in range(90):
        x = width * (0.06 + 0.86 * step / 89)
        loop = math.sin(step / 89 * frequency * math.pi + phase)
        points.append((x + 0.02 * width * math.cos(step), height * (0.5 - 0.3 * loop * rng.uniform(0.7, 1.0))))
    draw.line(points, fill=0, width=stroke, joint="curve")
    draw.line([(0.15 * width, 0.82 * height), (0.75 * width, 0.62 * height)], fill=0, width=stroke)
    return image


def emblem(size: int) -> Image.Image:
    """A seal-like logo: something visual on the page that is not personal data."""
    image = Image.new("L", (size, size), 255)
    draw = ImageDraw.Draw(image)
    for inset, width in ((2, 4), (size // 7, 2), (size // 3, 3)):
        draw.ellipse((inset, inset, size - inset, size - inset), outline=0, width=width)
    for angle in range(0, 360, 30):
        rad = math.radians(angle)
        draw.line(
            (size / 2, size / 2, size / 2 + 0.33 * size * math.cos(rad), size / 2 + 0.33 * size * math.sin(rad)),
            fill=0,
            width=2,
        )
    return image


def _ink_box(image: Image.Image, left: float, top: float) -> tuple[float, float, float, float]:
    x0, y0, x1, y1 = Image.eval(image, lambda value: 255 - value).getbbox() or (0, 0, image.width, image.height)
    return left + x0, top + y0, left + x1, top + y1


def _visual_label(
    sample: Sample, pii_type: str, box: tuple[float, float, float, float], size: tuple[float, float]
) -> None:
    width, height = size
    value = f"{box[0] / width:.4f},{box[1] / height:.4f},{box[2] / width:.4f},{box[3] / height:.4f}"
    sample.labels.append(Label(pii_type, value))


def _qr_payload(v: Values) -> str:
    # Half dense (like an Aadhaar secure QR code, a long run of digits), half short (a verification link).
    return v.digits(v.rng.choice((900, 1400))) if v.rng.random() < 0.5 else f"https://verify.example.in/{v.digits(12)}"


def visual_raster(v: Values, sample: Sample) -> Image.Image:
    """An ID page rendered as an image: text, a QR code, a signature over its caption, and a logo."""
    lines = ["Identity details", *record(v, sample)[:6]]
    rendered = {"NAME", "AADHAAR", "PAN", "PHONE", "EMAIL", "DATE_OF_BIRTH"}
    sample.labels = [label for label in sample.labels if label.pii_type in rendered]
    page = Image.new("L", (1700, 2200), 255)
    draw = ImageDraw.Draw(page)
    font = ImageFont.load_default(size=30)
    y = 300
    for line in lines:
        for part in line.split("\n"):
            draw.text((70, y), part, fill=0, font=font)
            y += 52
    page.paste(emblem(220), (70, 40))
    side = v.rng.randint(300, 420)
    qr_left, qr_top = 1700 - side - 120, v.rng.randint(1100, 1500)
    page.paste(qr_code(_qr_payload(v), side), (qr_left, qr_top))
    _visual_label(sample, "QR_CODE", (qr_left, qr_top, qr_left + side, qr_top + side), page.size)
    strokes = signature_strokes(v.rng, 460, 140)
    sig_left, sig_top = 120, y + 160
    page.paste(strokes, (sig_left, sig_top), mask=Image.eval(strokes, lambda value: 255 - value))
    draw.text((sig_left, sig_top + 160), "Signature of the holder", fill=0, font=font)
    _visual_label(sample, "SIGNATURE", _ink_box(strokes, sig_left, sig_top), page.size)
    return page.convert("RGB")


def write_visual_pdf(path: Path, v: Values, sample: Sample) -> None:
    """A text PDF that embeds a QR code and a signature as images, as digitally issued certificates do."""
    lines = ["Certificate of registration", *record(v, sample)[:6]]
    rendered = {"NAME", "AADHAAR", "PAN", "PHONE", "EMAIL", "DATE_OF_BIRTH"}
    sample.labels = [label for label in sample.labels if label.pii_type in rendered]
    document = pymupdf.open()
    page = document.new_page()
    y = 150
    for line in lines:
        for part in line.split("\n"):
            page.insert_text((60, y), part, fontsize=11)
            y += 20

    def png(image: Image.Image) -> bytes:
        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        return buffer.getvalue()

    page.insert_image(pymupdf.Rect(60, 40, 130, 110), stream=png(emblem(220)))
    side = v.rng.randint(80, 120)
    qr = pymupdf.Rect(480 - side, 600, 480, 600 + side)
    page.insert_image(qr, stream=png(qr_code(_qr_payload(v), 4 * side)))
    _visual_label(sample, "QR_CODE", (qr.x0, qr.y0, qr.x1, qr.y1), (page.rect.width, page.rect.height))
    strokes = signature_strokes(v.rng, 460, 140)
    target = pymupdf.Rect(80, y + 40, 80 + 138, y + 40 + 42)
    page.insert_image(target, stream=png(strokes))
    page.insert_text((80, target.y1 + 16), "Signature of the holder", fontsize=10)
    scale = target.width / strokes.width
    x0, y0, x1, y1 = _ink_box(strokes, 0, 0)
    ink = (target.x0 + x0 * scale, target.y0 + y0 * scale, target.x0 + x1 * scale, target.y0 + y1 * scale)
    _visual_label(sample, "SIGNATURE", ink, (page.rect.width, page.rect.height))
    document.save(str(path))
    document.close()


# --------------------------------------------------------------------------- generation


def table_rows(v: Values, sample: Sample, count: int) -> list[list[str]]:
    rows = [["Name", "PAN", "Aadhaar", "Mobile", "Invoice Number"]]
    for _ in range(count):
        name, pan, aadhaar, phone, invoice = v.name(), v.pan(), v.aadhaar(), v.phone(), v.digits(12)
        rows.append([name, pan, aadhaar, phone, invoice])
        sample.labels += [Label("NAME", name), Label("PAN", pan), Label("AADHAAR", aadhaar), Label("PHONE", phone)]
        sample.distractors.append(Distractor("invoice", invoice))
    return rows


def generate(split: str, seed: int, out: Path) -> list[Sample]:
    rng = random.Random(seed)
    v = Values(rng)
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    samples: list[Sample] = []

    def new(category: str, ext: str) -> tuple[Sample, Path]:
        index = sum(1 for s in samples if s.category == category) + 1
        name = f"{category}_{index:02d}.{ext}"
        sample = Sample(file=name, category=category)
        samples.append(sample)
        return sample, out / name

    for _ in range(6):  # clean documents: no PII, but plenty of look-alike numbers
        sample, path = new("clean", "txt")
        write_txt(path, ["Quarterly procurement summary", *distractors(v, sample, 6), "No personal data is included."])
    for style in ("plain", "spaced", "hyphen", "mixedcase", "split"):
        for _ in range(3):
            sample, path = new(f"multi_{style}", "txt")
            write_txt(
                path,
                [
                    "Employee application form",
                    *record(v, sample, style=style),
                    *distractors(v, sample, 3),
                    prose_line(v, sample),
                ],
            )
    for _ in range(6):  # single PII
        sample, path = new("single", "txt")
        kind = rng.choice(["PAN", "AADHAAR", "PASSPORT", "VOTER_ID", "DRIVING_LICENSE", "PHONE", "EMAIL"])
        value = {
            "PAN": v.pan,
            "AADHAAR": v.aadhaar,
            "PASSPORT": v.passport,
            "VOTER_ID": v.voter,
            "DRIVING_LICENSE": v.dl,
            "PHONE": v.phone,
            "EMAIL": lambda: v.email(v.name()),
        }[kind]()
        label = {
            "PAN": "PAN",
            "AADHAAR": "Aadhaar number",
            "PASSPORT": "Passport number",
            "VOTER_ID": "EPIC No",
            "DRIVING_LICENSE": "DL No",
            "PHONE": "Contact number",
            "EMAIL": "Email",
        }[kind]
        sample.labels.append(Label(kind, value))
        write_txt(path, ["Verification note", f"{label}: {value}", *distractors(v, sample, 2)])
    for _ in range(4):  # false-positive stress: labelled invalid Aadhaar + many distractors
        sample, path = new("false_positive", "txt")
        bad = v.invalid_aadhaar()
        sample.distractors.append(Distractor("invalid_checksum_aadhaar", bad))
        write_txt(path, ["Payment register", *distractors(v, sample, 8), f"Aadhaar (as typed by applicant): {bad}"])
    for _ in range(3):
        sample, path = new("table", "csv")
        rows = table_rows(v, sample, 6)
        with path.open("w", newline="", encoding="utf-8") as handle:
            csv.writer(handle).writerows(rows)
    for _ in range(3):
        sample, path = new("table", "xlsx")
        rows = table_rows(v, sample, 6)
        workbook = Workbook()
        sheet = workbook.active
        for row in rows:
            sheet.append(row)
        workbook.save(path)
    for _ in range(3):
        sample, path = new("structured", "json")
        people = []
        for _ in range(3):
            name, pan, phone = v.name(), v.pan(), v.phone()
            email = v.email(name)
            people.append(
                {
                    "full_name": name,
                    "pan": pan,
                    "mobile": phone,
                    "email": email,
                    "order_id": v.letters(3) + v.digits(7),
                }
            )
            sample.labels += [Label("NAME", name), Label("PAN", pan), Label("PHONE", phone), Label("EMAIL", email)]
        path.write_text(json.dumps({"customers": people}, indent=2), encoding="utf-8")
    for _ in range(3):
        sample, path = new("structured", "xml")
        parts = ["<?xml version='1.0' encoding='utf-8'?>", "<employees>"]
        for _ in range(3):
            name, aadhaar, voter = v.name(), v.aadhaar(), v.voter()
            parts.append(
                f"  <employee><name>{escape(name)}</name><aadhaar>{aadhaar}</aadhaar>"
                f"<voter_id>{voter}</voter_id><employee_id>{v.letters(1)}{v.digits(7)}</employee_id></employee>"
            )
            sample.labels += [Label("NAME", name), Label("AADHAAR", aadhaar), Label("VOTER_ID", voter)]
        parts.append("</employees>")
        path.write_text("\n".join(parts), encoding="utf-8")
    for _ in range(4):
        sample, path = new("docx", "docx")
        lines = ["Tenant verification form", *record(v, sample), *distractors(v, sample, 2)]
        table = [["Reference", "Contact"], [f"Ref no: {v.letters(4)}{v.digits(6)}", "Office"]]
        write_docx(path, lines, table)
    for _ in range(4):
        sample, path = new("pdf_text", "pdf")
        page1 = ["Loan application", *record(v, sample, page=1)]
        page2 = ["Annexure", *distractors(v, sample, 3)]
        extra = v.pan()
        page2.append(f"Co-applicant PAN: {extra}")
        sample.labels.append(Label("PAN", extra, 2))
        write_pdf(path, [page1, page2])
    for _ in range(3):
        sample, path = new("pdf_scanned", "pdf")
        write_scanned_pdf(path, ["Scanned KYC form", *record(v, sample)], rng)
    for noisy, category in ((False, "image"), (True, "image_ocr_noise")):
        for _ in range(3):
            sample, path = new(category, "png")
            # Only the first six record lines are rendered; keep exactly their labels.
            lines = ["Identity details", *record(v, sample)[:6]]
            rendered = {"NAME", "AADHAAR", "PAN", "PHONE", "EMAIL", "DATE_OF_BIRTH"}
            sample.labels = [label for label in sample.labels if label.pii_type in rendered]
            text_image(lines, noisy=noisy, rng=rng).save(path)
    # Added with detector 1.1.0. Generated last, so every earlier document stays identical for a given seed.
    for _ in range(2):
        sample, path = new("aadhaar_letter", "pdf")
        write_pdf(path, [aadhaar_letter(v, sample)])
    for _ in range(2):
        sample, path = new("aadhaar_letter_scanned", "pdf")
        write_scanned_pdf(path, aadhaar_letter(v, sample), rng)
    # Added with detector 1.2.0 (labels for enrolment numbers, places of birth, roll numbers and marks: 1.3.0).
    for _ in range(3):
        sample, path = new("passport_scanned", "pdf")
        write_scanned_pdf(path, passport_page(v, sample), rng)
    for _ in range(3):
        sample, path = new("certificate", "pdf")
        write_pdf(path, [school_certificate(v, sample)])
    # Added with detector 1.4.0: QR codes and signatures (and a logo that is neither), with their boxes.
    for _ in range(2):
        sample, path = new("visual_scanned", "pdf")
        image = visual_raster(v, sample)
        tmp = path.with_suffix(".png")
        image.save(tmp)
        document = pymupdf.open()
        page = document.new_page(width=612, height=612 * image.height / image.width)
        page.insert_image(page.rect, filename=str(tmp))
        document.save(str(path))
        document.close()
        tmp.unlink()
    for _ in range(2):
        sample, path = new("visual_image", "png")
        visual_raster(v, sample).save(path)
    for _ in range(2):
        sample, path = new("visual_pdf", "pdf")
        write_visual_pdf(path, v, sample)

    manifest = {
        "split": split,
        "seed": seed,
        "generated": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
        "note": "Synthetic data only. Identifier values are random and match documented structures.",
        "samples": [asdict(sample) for sample in samples],
    }
    (out / "ground_truth.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return samples


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--split", default="dev")
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--out", type=Path, default=ROOT / "dataset" / "synthetic")
    args = parser.parse_args()
    samples = generate(args.split, args.seed, args.out / args.split)
    labels = sum(len(sample.labels) for sample in samples)
    negatives = sum(len(sample.distractors) for sample in samples)
    print(f"{args.split}: {len(samples)} documents, {labels} labelled PII values, {negatives} distractors")


if __name__ == "__main__":
    main()
