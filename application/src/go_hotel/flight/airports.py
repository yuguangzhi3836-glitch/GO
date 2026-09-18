"""Deterministic multilingual airport/city resolver for flight search.

Only exact normalized aliases are accepted.  Deliberately no fuzzy matching: a
misspelling must be corrected by the traveler instead of silently selecting the
wrong airport.
"""
from __future__ import annotations

from dataclasses import dataclass
import re
import unicodedata


@dataclass(frozen=True)
class Airport:
    iata: str
    city: str
    name: str
    aliases: tuple[str, ...]


class AirportResolutionError(ValueError):
    def __init__(self, code: str, query: str, candidates: tuple[str, ...] = ()):
        super().__init__(code)
        self.code = code
        self.query = query
        self.candidates = candidates


AIRPORTS = (
    Airport('PVG', 'Shanghai', 'Shanghai Pudong International Airport',
            ('上海浦东国际机场', '上海浦东机场', '浦东机场', 'Shanghai Pudong', 'Pudong Airport')),
    Airport('SHA', 'Shanghai', 'Shanghai Hongqiao International Airport',
            ('上海虹桥国际机场', '上海虹桥机场', '虹桥机场', 'Shanghai Hongqiao', 'Hongqiao Airport')),
    Airport('PEK', 'Beijing', 'Beijing Capital International Airport',
            ('北京首都国际机场', '北京首都机场', '首都机场', 'Beijing Capital', 'Pékin Capitale')),
    Airport('PKX', 'Beijing', 'Beijing Daxing International Airport',
            ('北京大兴国际机场', '北京大兴机场', '大兴机场', 'Beijing Daxing')),
    Airport('CAN', 'Guangzhou', 'Guangzhou Baiyun International Airport',
            ('广州白云国际机场', '广州白云机场', '白云机场', 'Guangzhou Baiyun', '广州', 'Guangzhou')),
    Airport('SZX', 'Shenzhen', 'Shenzhen Baoan International Airport',
            ('深圳宝安国际机场', '深圳宝安机场', '宝安机场', 'Shenzhen Baoan', '深圳', 'Shenzhen')),
    Airport('XMN', 'Xiamen', 'Xiamen Gaoqi International Airport',
            ('厦门高崎国际机场', '厦门高崎机场', '高崎机场', 'Xiamen Gaoqi', '厦门', 'Xiamen')),
    Airport('FOC', 'Fuzhou', 'Fuzhou Changle International Airport',
            ('福州长乐国际机场', '福州长乐机场', '长乐机场', 'Fuzhou Changle', '福州', 'Fuzhou')),
    Airport('HRB', 'Harbin', 'Harbin Taiping International Airport',
            ('哈尔滨太平国际机场', '哈尔滨太平机场', '太平机场', 'Harbin Taiping', '哈尔滨', 'Harbin')),
    Airport('HKG', 'Hong Kong', 'Hong Kong International Airport',
            ('香港国际机场', '香港机场', 'Hong Kong Airport', '香港', 'Hong Kong')),
    Airport('SIN', 'Singapore', 'Singapore Changi Airport',
            ('新加坡樟宜机场', '樟宜机场', 'Singapore Changi', 'Changi Airport', '新加坡', 'Singapore')),
    Airport('HND', 'Tokyo', 'Tokyo Haneda Airport',
            ('东京羽田机场', '東京羽田空港', '羽田机场', '羽田空港', 'Tokyo Haneda', 'Haneda Airport')),
    Airport('NRT', 'Tokyo', 'Narita International Airport',
            ('东京成田机场', '東京成田空港', '成田机场', '成田空港', 'Tokyo Narita', 'Narita Airport')),
    Airport('KIX', 'Osaka', 'Kansai International Airport',
            ('大阪关西国际机场', '関西国際空港', '关西机场', 'Kansai Airport', 'Osaka Kansai')),
    Airport('ICN', 'Seoul', 'Incheon International Airport',
            ('首尔仁川国际机场', '인천국제공항', '仁川机场', 'Seoul Incheon', 'Incheon Airport')),
    Airport('CDG', 'Paris', 'Paris Charles de Gaulle Airport',
            ('巴黎戴高乐机场', 'Aéroport de Paris-Charles-de-Gaulle', 'Paris Charles de Gaulle', 'Roissy CDG')),
    Airport('LHR', 'London', 'London Heathrow Airport',
            ('伦敦希思罗机场', 'London Heathrow', 'Heathrow Airport')),
    Airport('JFK', 'New York', 'John F. Kennedy International Airport',
            ('纽约肯尼迪机场', 'New York JFK', 'Kennedy Airport')),
)

CITY_ALIASES = {
    'Shanghai': ('上海', 'Shanghai'),
    'Beijing': ('北京', 'Beijing', 'Pékin'),
    'Tokyo': ('东京', '東京', 'Tokyo'),
    'Paris': ('巴黎', 'Paris'),
    'London': ('伦敦', 'London'),
    'New York': ('纽约', 'New York', 'Nueva York'),
}


def _key(value: str) -> str:
    if not isinstance(value, str):
        return ''
    folded = unicodedata.normalize('NFKD', unicodedata.normalize('NFKC', value).casefold())
    folded = ''.join(ch for ch in folded if not unicodedata.combining(ch))
    return re.sub(r'[^0-9a-z\u3400-\u9fff\u3040-\u30ff\uac00-\ud7af]+', '', folded)


def _index() -> dict[str, set[str]]:
    result: dict[str, set[str]] = {}
    for airport in AIRPORTS:
        values = (airport.iata, airport.name, *airport.aliases)
        for value in values:
            result.setdefault(_key(value), set()).add(airport.iata)
        for alias in CITY_ALIASES.get(airport.city, ()):
            result.setdefault(_key(alias), set()).add(airport.iata)
    return result


INDEX = _index()
BY_IATA = {airport.iata: airport for airport in AIRPORTS}


def resolve_airport(value: str) -> dict[str, str]:
    query = value.strip() if isinstance(value, str) else ''
    matches = tuple(sorted(INDEX.get(_key(query), ())))
    if not matches:
        raise AirportResolutionError('AIRPORT_NOT_FOUND', query)
    if len(matches) != 1:
        raise AirportResolutionError('AIRPORT_AMBIGUOUS', query, matches)
    airport = BY_IATA[matches[0]]
    return {'input': query, 'iata': airport.iata, 'city': airport.city, 'name': airport.name}
