# -*- coding: utf-8 -*-
"""
Извлечение цены со страницы товара — без указания CSS-селектора.

Слои (по убыванию надёжности):
  1. JSON-LD (schema.org Product/Offer → offers.price)
  2. meta-теги (og:price:amount, product:price:amount, itemprop=price)
  3. типовые элементы с классом *price*
  4. регэксп по тексту страницы (₽, руб, $, €)

Возвращает (amount: float|None, raw: str|None, currency: str|None).
"""

import json
import re

from bs4 import BeautifulSoup

CURRENCY_SIGNS = {
    "₽": "RUB", "руб": "RUB", "р.": "RUB", "rub": "RUB",
    "$": "USD", "usd": "USD",
    "€": "EUR", "eur": "EUR",
    "£": "GBP", "gbp": "GBP",
    "₴": "UAH", "грн": "UAH",
}


def _to_number(text: str):
    """'1 299,00 ₽' -> 1299.0"""
    if text is None:
        return None
    cleaned = re.sub(r"[^\d.,]", "", str(text))
    if not cleaned:
        return None
    # если есть и точка, и запятая — последняя из них десятичный разделитель
    if "," in cleaned and "." in cleaned:
        if cleaned.rfind(",") > cleaned.rfind("."):
            cleaned = cleaned.replace(".", "").replace(",", ".")
        else:
            cleaned = cleaned.replace(",", "")
    elif "," in cleaned:
        # запятая как десятичный разделитель только если 1-2 знака после
        if re.search(r",\d{1,2}$", cleaned):
            cleaned = cleaned.replace(",", ".")
        else:
            cleaned = cleaned.replace(",", "")
    try:
        return float(cleaned)
    except ValueError:
        return None


def _detect_currency(text: str):
    low = text.lower()
    for sign, code in CURRENCY_SIGNS.items():
        if sign in low:
            return code
    return None


def _from_jsonld(soup: BeautifulSoup):
    for tag in soup.find_all("script", attrs={"type": "application/ld+json"}):
        try:
            data = json.loads(tag.string or "")
        except (json.JSONDecodeError, TypeError):
            continue
        for node in data if isinstance(data, list) else [data]:
            if not isinstance(node, dict):
                continue
            offers = node.get("offers")
            if isinstance(offers, list):
                offers = offers[0] if offers else None
            if isinstance(offers, dict) and offers.get("price") is not None:
                return _to_number(offers["price"]), str(offers["price"]), offers.get("priceCurrency")
    return None


def _from_meta(soup: BeautifulSoup):
    selectors = [
        ("meta", {"property": "product:price:amount"}, "content"),
        ("meta", {"property": "og:price:amount"}, "content"),
        ("meta", {"itemprop": "price"}, "content"),
    ]
    for name, attrs, attr in selectors:
        tag = soup.find(name, attrs=attrs)
        if tag and tag.get(attr):
            val = tag.get(attr)
            return _to_number(val), val, None
    return None


def _from_elements(soup: BeautifulSoup):
    candidate = soup.find(attrs={"class": re.compile("price", re.I)})
    if candidate:
        text = candidate.get_text(" ", strip=True)
        num = _to_number(text)
        if num is not None:
            return num, text, _detect_currency(text)
    return None


def _from_regex(soup: BeautifulSoup):
    text = soup.get_text(" ", strip=True)
    match = re.search(r"(\d[\d  .,]{2,})\s*(₽|руб|\$|€|£|грн)", text, re.I)
    if match:
        raw = match.group(0)
        return _to_number(match.group(1)), raw, _detect_currency(match.group(2))
    return None


def extract_price(html: str):
    soup = BeautifulSoup(html, "lxml")
    for layer in (_from_jsonld, _from_meta, _from_elements, _from_regex):
        result = layer(soup)
        if result and result[0] is not None:
            return result
    return None, None, None
