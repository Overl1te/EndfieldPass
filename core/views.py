"""Main application views and import/sync orchestration.

This module contains:
- dashboard/characters rendering logic
- history import/export flows
- OAuth cloud connection and cloud sync endpoints
- asynchronous import progress tracking
"""

import json
import re
import secrets
import threading
import time
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs, urljoin, urlparse

from django.conf import settings
from django.http import HttpResponseBadRequest, JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.csrf import csrf_exempt

from .cloud import (
    CLOUD_PROVIDER_CHOICES,
    SYNC_FILE_NAME,
    SYNC_FOLDER_NAME,
    SYNC_PROVIDER_CHOICES,
    CloudIntegrationError,
    build_oauth_authorization_url,
    exchange_oauth_code,
    export_payload_to_cloud,
    import_payload_from_cloud,
    refresh_oauth_token,
)
from .localization import (
    SITE_LANGUAGE_COOKIE_KEY,
    SITE_LANGUAGE_SESSION_KEY,
    get_request_language,
    normalize_language_code,
    translate,
)
from .services import fetch_all_records


IMPORT_PROGRESS = {}
IMPORT_PROGRESS_LOCK = threading.Lock()
IMPORT_SESSIONS = {}
IMPORT_SESSION_COUNTER = 0

POOL_LABELS = {
    "E_CharacterGachaPoolType_Standard": "dashboard.pool.standard",
    "E_CharacterGachaPoolType_Special": "dashboard.pool.character",
    "E_CharacterGachaPoolType_Beginner": "dashboard.pool.beginner",
}

DASHBOARD_POOLS = [
    {
        "title_key": "dashboard.pool.character",
        "source_pool_type": "E_CharacterGachaPoolType_Special",
        "pool_id_fallback": "special",
        "six_star_limit": 80,
        "five_star_limit": 10,
    },
    {
        "title_key": "dashboard.pool.standard",
        "source_pool_type": "E_CharacterGachaPoolType_Standard",
        "pool_id_fallback": "standard",
        "six_star_limit": 80,
        "five_star_limit": 10,
    },
    {
        "title_key": "dashboard.pool.beginner",
        "source_pool_type": "E_CharacterGachaPoolType_Beginner",
        "pool_id_fallback": "beginner",
        "six_star_limit": 80,
        "five_star_limit": 10,
    },
    {
        "title_key": "dashboard.pool.weapon",
        "source_pool_type": "E_WeaponGachaPoolType_Weapon",
        "pool_id_fallback": "weponbox",
        "six_star_limit": 40,
        "five_star_limit": 10,
    },
]

OFFICIAL_REPOSITORY_URL = "https://github.com/Overl1te/EndfieldPass"
DEFAULT_DONATE_URL = "https://github.com/sponsors/Overl1te"

CLOUD_AUTH_SESSION_KEY = "cloud_auth"
CLOUD_OAUTH_STATE_SESSION_KEY = "cloud_oauth_state"
SETTINGS_FLASH_SESSION_KEY = "settings_flash"


def _tr_lang(language, key, **kwargs):
    """Translate a key for the provided language code."""
    return translate(language, key, **kwargs)


def _tr(request, key, **kwargs):
    """Translate a key based on current request language."""
    return _tr_lang(get_request_language(request), key, **kwargs)


CHARACTER_ELEMENTS = {
    "heat": {"label_key": "character.element.heat", "icon": "Heaticon.webp"},
    "cryo": {"label_key": "character.element.cryo", "icon": "Cryoicon.webp"},
    "electric": {"label_key": "character.element.electric", "icon": "Electricicon.webp"},
    "nature": {"label_key": "character.element.nature", "icon": "Natureicon.webp"},
    "physical": {"label_key": "character.element.physical", "icon": "Physicalicon.webp"},
}

CHARACTER_WEAPONS = {
    "short": {"label_key": "character.weapon.short", "icon": "Short-Weapon.webp"},
    "great": {"label_key": "character.weapon.great", "icon": "Great-Weapon.webp"},
    "guns": {"label_key": "character.weapon.guns", "icon": "Guns.webp"},
    "polearms": {"label_key": "character.weapon.polearms", "icon": "Polearms.webp"},
    "orbiters": {"label_key": "character.weapon.orbiters", "icon": "Orbiters.webp"},
}

CHARACTER_ROLES = {
    "caster": {"label_key": "character.role.caster", "icon": "Caster.webp"},
    "defender": {"label_key": "character.role.defender", "icon": "Defender.webp"},
    "guard": {"label_key": "character.role.guard", "icon": "Guard.webp"},
    "striker": {"label_key": "character.role.striker", "icon": "Striker.webp"},
    "support": {"label_key": "character.role.support", "icon": "Support.webp"},
    "vanguard": {"label_key": "character.role.vanguard", "icon": "Vanguard.webp"},
}

RARITY_ICONS = {
    4: "4-Stars.webp",
    5: "5-Stars.webp",
    6: "6-Stars.webp",
}

CHARACTERS = [
    {"name": "Акэкури", "icon": "akekuri.png", "rarity": 4, "element": "heat", "weapon": "short", "role": "striker", "aliases": ["Akekuri"]},
    {"name": "Алеш", "icon": "alesh.png", "rarity": 5, "element": "cryo", "weapon": "short", "role": "vanguard", "aliases": ["Alesh"]},
    {"name": "Антал", "icon": "antal.png", "rarity": 4, "element": "electric", "weapon": "orbiters", "role": "guard", "aliases": ["Antal"]},
    {"name": "Арклайт", "icon": "arclight.png", "rarity": 5, "element": "electric", "weapon": "short", "role": "striker", "aliases": ["Arclight"]},
    {"name": "Арделия", "icon": "Ardelia.png", "rarity": 6, "element": "nature", "weapon": "orbiters", "role": "support", "aliases": ["Ardelia"]},
    {"name": "Авивенна", "icon": "avywenna.png", "rarity": 5, "element": "electric", "weapon": "polearms", "role": "vanguard", "aliases": ["Avywenna"]},
    {"name": "Кэтчер", "icon": "catcher.png", "rarity": 4, "element": "physical", "weapon": "great", "role": "striker", "aliases": ["Catcher"]},
    {"name": "Чэнь Цяньюй", "icon": "Chen-Qianyu.png", "rarity": 5, "element": "physical", "weapon": "short", "role": "support", "aliases": ["Chen Qianyu", "Chen-Qianyu"]},
    {"name": "Да Пан", "icon": "da-pan.png", "rarity": 5, "element": "physical", "weapon": "great", "role": "defender", "aliases": ["Da Pan", "Da-Pan"]},
    {"name": "Эмбер", "icon": "ember.png", "rarity": 6, "element": "heat", "weapon": "great", "role": "guard", "aliases": ["Ember"]},
    {"name": "Эндминистратор", "icon": "Endministrator.png", "rarity": 6, "element": "physical", "weapon": "short", "role": "guard", "aliases": ["Endministrator"]},
    {"name": "Эстелла", "icon": "estella.png", "rarity": 4, "element": "cryo", "weapon": "polearms", "role": "caster", "aliases": ["Estella"]},
    {"name": "Флюорит", "icon": "fluorite.png", "rarity": 4, "element": "nature", "weapon": "guns", "role": "caster", "aliases": ["Fluorite", "Фрюорит"]},
    {"name": "Гилберта", "icon": "gilberta.png", "rarity": 6, "element": "nature", "weapon": "orbiters", "role": "support", "aliases": ["Gilberta"]},
    {"name": "Лэватейн", "icon": "laevatain.png", "rarity": 6, "element": "heat", "weapon": "short", "role": "guard", "aliases": ["Laevatain"]},
    {"name": "Панихида", "icon": "last-rite.png", "rarity": 6, "element": "cryo", "weapon": "great", "role": "caster", "aliases": ["Last Rite", "Last-Rite"]},
    {"name": "Лифэн", "icon": "lifeng.png", "rarity": 6, "element": "physical", "weapon": "polearms", "role": "vanguard", "aliases": ["Lifeng"]},
    {"name": "Перлика", "icon": "perlica.png", "rarity": 5, "element": "electric", "weapon": "orbiters", "role": "support", "aliases": ["Perlica"]},
    {"name": "Пограничник", "icon": "pogranichnik.png", "rarity": 6, "element": "physical", "weapon": "short", "role": "defender", "aliases": ["Pogranichnik"]},
    {"name": "Светоснежка", "icon": "snowshine.png", "rarity": 5, "element": "cryo", "weapon": "great", "role": "support", "aliases": ["Snowshine"]},
    {"name": "Вулфгард", "icon": "wulfgard.png", "rarity": 5, "element": "heat", "weapon": "guns", "role": "striker", "aliases": ["Wulfgard"]},
    {"name": "Сайхи", "icon": "xaihi.png", "rarity": 5, "element": "cryo", "weapon": "orbiters", "role": "support", "aliases": ["Xaihi"]},
    {"name": "Ивонна", "icon": "yvonne.png", "rarity": 6, "element": "cryo", "weapon": "guns", "role": "caster", "aliases": ["Yvonne"]},
]

CHARACTER_OFFICIAL_NAMES = {
    "akekuri.png": {"ru": "Акэкури", "en": "Akekuri", "de": "Akekuri", "zh-hans": "红栗", "ja": "アケクリ"},
    "alesh.png": {"ru": "Алеш", "en": "Alesh", "de": "Alesh", "zh-hans": "阿列什", "ja": "アレッシュ"},
    "antal.png": {"ru": "Антал", "en": "Antal", "de": "Antal", "zh-hans": "安塔尔", "ja": "アンタル"},
    "arclight.png": {"ru": "Арклайт", "en": "Arclight", "de": "Arclight", "zh-hans": "弧光", "ja": "アークライト"},
    "Ardelia.png": {"ru": "Арделия", "en": "Ardelia", "de": "Ardelia", "zh-hans": "艾尔黛拉", "ja": "アルデリア"},
    "avywenna.png": {"ru": "Авивенна", "en": "Avywenna", "de": "Avywenna", "zh-hans": "艾维文娜", "ja": "アイヴィーエナ"},
    "catcher.png": {"ru": "Кэтчер", "en": "Catcher", "de": "Catcher", "zh-hans": "卡契尔", "ja": "キャッチャー"},
    "Chen-Qianyu.png": {"ru": "Чэнь Цяньюй", "en": "Chen Qianyu", "de": "Chen Qianyu", "zh-hans": "陈千语", "ja": "チェン・センユー"},
    "da-pan.png": {"ru": "Да Пан", "en": "Da Pan", "de": "Da Pan", "zh-hans": "大潘", "ja": "ダパン"},
    "ember.png": {"ru": "Эмбер", "en": "Ember", "de": "Ember", "zh-hans": "余烬", "ja": "エンバー"},
    "Endministrator.png": {"ru": "Эндминистратор", "en": "Endministrator", "de": "Endministrator", "zh-hans": "管理员", "ja": "管理人"},
    "estella.png": {"ru": "Эстелла", "en": "Estella", "de": "Estella", "zh-hans": "埃特拉", "ja": "エステーラ"},
    "fluorite.png": {"ru": "Флюорит", "en": "Fluorite", "de": "Fluorite", "zh-hans": "萤石", "ja": "フローライト"},
    "gilberta.png": {"ru": "Гилберта", "en": "Gilberta", "de": "Gilberta", "zh-hans": "洁尔佩塔", "ja": "ギルベルタ"},
    "laevatain.png": {"ru": "Лэватейн", "en": "Laevatain", "de": "Laevatain", "zh-hans": "莱万汀", "ja": "レーヴァティン"},
    "last-rite.png": {"ru": "Панихида", "en": "Last Rite", "de": "Last Rite", "zh-hans": "别礼", "ja": "ラストライト"},
    "lifeng.png": {"ru": "Лифэн", "en": "Lifeng", "de": "Lifeng", "zh-hans": "黎风", "ja": "リーフォン"},
    "perlica.png": {"ru": "Перлика", "en": "Perlica", "de": "Perlica", "zh-hans": "佩丽卡", "ja": "ペリカ"},
    "pogranichnik.png": {"ru": "Пограничник", "en": "Pogranichnik", "de": "Pogranichnik", "zh-hans": "骏卫", "ja": "ポグラニチニク"},
    "snowshine.png": {"ru": "Светоснежка", "en": "Snowshine", "de": "Snowshine", "zh-hans": "昼雪", "ja": "スノーシャイン"},
    "wulfgard.png": {"ru": "Вулфгард", "en": "Wulfgard", "de": "Wulfgard", "zh-hans": "狼卫", "ja": "ウルフガード"},
    "xaihi.png": {"ru": "Сайхи", "en": "Xaihi", "de": "Xaihi", "zh-hans": "赛希", "ja": "ザイヒ"},
    "yvonne.png": {"ru": "Ивонна", "en": "Yvonne", "de": "Yvonne", "zh-hans": "伊冯", "ja": "イヴォンヌ"},
}

WEAPON_OFFICIAL_NAMES = {
    "Джимини 12": {"ru": "Джимини 12", "en": "Jiminy 12", "de": "Jiminy 12", "zh-hans": "吉米尼12", "ja": "ジミニ12"},
    "Оперо 77": {"ru": "Оперо 77", "en": "Opero 77", "de": "Opero 77", "zh-hans": "奥佩罗77", "ja": "オッペロ77"},
    "Пеко 5": {"ru": "Пеко 5", "en": "Peco 5", "de": "Peco 5", "zh-hans": "佩科5", "ja": "ペッコ5"},
    "Тарр 11": {"ru": "Тарр 11", "en": "Tarr 11", "de": "Tarr 11", "zh-hans": "塔尔11", "ja": "タール11"},
    "Дархофф 7": {"ru": "Дархофф 7", "en": "Darhoff 7", "de": "Darhoff 7", "zh-hans": "达尔霍夫7", "ja": "ダルホフ7"},
    "Гаситель": {"ru": "Гаситель", "en": "Quencher", "de": "Ausloscher", "zh-hans": "淬火者", "ja": "鍛冶師"},
    "Гиперновая": {"ru": "Гиперновая", "en": "Hypernova Auto", "de": "Vollautomatische Hypernova", "zh-hans": "全自动焕新星", "ja": "オート・ハイパーノヴァ"},
    "Долгий путь": {"ru": "Долгий путь", "en": "Long Road", "de": "Langer Weg", "zh-hans": "长路", "ja": "長路"},
    "Индустрия 0.1": {"ru": "Индустрия 0.1", "en": "Industry 0.1", "de": "Industrie 0.1", "zh-hans": "工业零点一", "ja": "工業零点一"},
    "Морской вал": {"ru": "Морской вал", "en": "Wave Tide", "de": "Flutwelle", "zh-hans": "浪潮", "ja": "潮流"},
    "Ревущий страж": {"ru": "Ревущий страж", "en": "Howling Guard", "de": "Heulender Wachter", "zh-hans": "呼啸守卫", "ja": "ロアーガード"},
    "Флуоресценция": {"ru": "Флуоресценция", "en": "Fluorescent Roc", "de": "Fluoreszierende Drohne", "zh-hans": "荧光雷羽", "ja": "蛍光雷羽"},
    "Чрезвычайная мера": {"ru": "Чрезвычайная мера", "en": "Contingent Measure", "de": "Notfallmaßnahme", "zh-hans": "应急手段", "ja": "緊急設計"},
    "Аггелоубийца": {"ru": "Аггелоубийца", "en": "Aggeloslayer", "de": "Aggelo-Bezwinger", "zh-hans": "天使杀手", "ja": "アンゲロス・スレイヤー"},
    "OBJ Идентификатор": {"ru": "OBJ Идентификатор искусств", "en": "OBJ Arts Identifier", "de": "OBJ Techniken-Bestimmer", "zh-hans": "O.B.J.术识", "ja": "O.B.J.術識"},
    "OBJ Клинок света": {"ru": "OBJ Клинок света", "en": "OBJ Edge of Lightness", "de": "OBJ Ende der Leichtigkeit", "zh-hans": "O.B.J.轻芒", "ja": "O.B.J.軽刃"},
    "OBJ Прыть Иконка": {"ru": "OBJ Прыть", "en": "OBJ Velocitous", "de": "OBJ Windeseile", "zh-hans": "O.B.J.迅极", "ja": "O.B.J.迅速"},
    "OBJ Рог-бритва": {"ru": "OBJ Рог-бритва", "en": "OBJ Razorhorn", "de": "OBJ Klingenhorn", "zh-hans": "O.B.J.尖峰", "ja": "O.B.J.鋭矛"},
    "OBJ Тяжёлое бремя": {"ru": "OBJ Тяжёлое бремя", "en": "OBJ Heavy Burden", "de": "OBJ Schwere Last", "zh-hans": "O.B.J.重荷", "ja": "O.B.J.重責"},
    "Водоплаволов 3.0": {"ru": "Водоплаволов 3.0", "en": "Finchaser 3.0", "de": "Flosslerjager 3.0", "zh-hans": "逐鳞3.0", "ja": "フィンチェイサー3.0"},
    "Двенадцать вопросов": {"ru": "Двенадцать вопросов", "en": "Twelve Questions", "de": "Zwolf Fragen", "zh-hans": "十二问", "ja": "十二問"},
    "Дикий странник": {"ru": "Дикий странник", "en": "Wild Wanderer", "de": "Wilder Wanderer", "zh-hans": "迷失荒野", "ja": "荒野迷走"},
    "Древний канал": {"ru": "Древний канал", "en": "Ancient Canal", "de": "Uralter Kanal", "zh-hans": "古渠", "ja": "千古恒常"},
    "Искатель тёмного луна": {"ru": "Искатель тёмного луна", "en": "Seeker of Dark Lung", "de": "Sucher der dunklen Lung", "zh-hans": "探颚", "ja": "探龍"},
    "Монаихэ": {"ru": "Монаихэ", "en": "Monaihe", "de": "Monaihe", "zh-hans": "莫奈何", "ja": "衒無"},
    "Опус живого": {"ru": "Опус живого", "en": "Opus: The Living", "de": "Opus: Die Lebenden", "zh-hans": "作品：众生", "ja": "作品：衆生"},
    "Прощальный обет": {"ru": "Прощальный обет", "en": "Rational Farewell", "de": "Rationaler Abschied", "zh-hans": "理性告别", "ja": "合理的決別"},
    "Свободное служение": {"ru": "Свободное служение", "en": "Freedom to Proselytize", "de": "Freiheit des Predigers", "zh-hans": "布道自由", "ja": "布教の自由"},
    "Скала": {"ru": "Скала", "en": "Fortmaker", "de": "Fortbauer", "zh-hans": "坚城铸造者", "ja": "堅城錬造者"},
    "Стальной раскол": {"ru": "Стальной раскол", "en": "Sundering Steel", "de": "ZerreiBender Stahl", "zh-hans": "钢铁余音", "ja": "鋼鉄余音"},
    "Станс памяти": {"ru": "Станс памяти", "en": "Stanza of Memorials", "de": "Strophe der Erinnerungen", "zh-hans": "悼亡诗", "ja": "弔いの詩"},
    "Устремление": {"ru": "Устремление", "en": "Aspirant", "de": "Aspirant", "zh-hans": "仰止", "ja": "仰止"},
    "Финальный вызов": {"ru": "Финальный вызов", "en": "Finishing Call", "de": "Finaler Schrei", "zh-hans": "终点之声", "ja": "最期の声"},
    "Химера правосудия": {"ru": "Химера правосудия", "en": "Chimeric Justice", "de": "Chimarische Gerechtigkeit", "zh-hans": "嵌合正义", "ja": "正義嵌合"},
    "Артист Тиранический": {"ru": "Артист Тиранический", "en": "Artzy Tyrannical", "de": "Kunstlerischer Tyrann", "zh-hans": "艺术暴君", "ja": "芸術の独裁者"},
    "Безупречная репутация": {"ru": "Безупречная репутация", "en": "Eminent Repute", "de": "Untadeliger Ruf", "zh-hans": "显赫声名", "ja": "輝かしき名声"},
    "Былой шик": {"ru": "Былой шик", "en": "Former Finery", "de": "Ehemalige Eleganz", "zh-hans": "昔日精品", "ja": "昔日の逸品"},
    "Великое видение": {"ru": "Великое видение", "en": "Grand Vision", "de": "GroBe Vision", "zh-hans": "宏愿", "ja": "大願"},
    "Гарантированная доставка": {"ru": "Гарантированная доставка", "en": "Delivery Guaranteed", "de": "Garantierte Lieferung", "zh-hans": "使命必达", "ja": "使命必達"},
    "Гнев кузни": {"ru": "Гнев кузни", "en": "Forgeborn Scathe", "de": "Tadel des Schmiedefeuers", "zh-hans": "熔铸火焰", "ja": "フレイムフォージ"},
    "Громберг": {"ru": "Громберг", "en": "Thunderberge", "de": "Donnerberg", "zh-hans": "大雷斑", "ja": "大雷斑"},
    "Доблесть": {"ru": "Доблесть", "en": "Valiant", "de": "Tapferkeit", "zh-hans": "骁勇", "ja": "勇猛"},
    "Забвение": {"ru": "Забвение", "en": "Oblivion", "de": "Vergessenheit", "zh-hans": "遗忘", "ja": "遺忘"},
    "Звезда белых ночей": {"ru": "Звезда белых ночей", "en": "White Night Nova", "de": "Polarnacht-Nova", "zh-hans": "白夜新星", "ja": "白夜新星"},
    "Кланнибал": {"ru": "Кланнибал", "en": "Clannibal", "de": "Klannibale", "zh-hans": "同类相食", "ja": "同類共食"},
    "Клин": {"ru": "Клин", "en": "Wedge", "de": "Keil", "zh-hans": "楔子", "ja": "楔"},
    "Мечта о звёздном береге": {"ru": "Мечта о звёздном береге", "en": "Dreams of the Starry Beach", "de": "Traume vom Sternenstrand", "zh-hans": "沧泪星梦", "ja": "蒼星の囁き"},
    "Модуль взрыва": {"ru": "Модуль взрыва", "en": "Detonation Unit", "de": "Zunder", "zh-hans": "爆破单元", "ja": "破壊ユニット"},
    "Навигатор": {"ru": "Навигатор", "en": "Navigator", "de": "Navigator", "zh-hans": "领航者", "ja": "ナビゲーター"},
    "Неустанность": {"ru": "Неустанность", "en": "Never Rest", "de": "Nimmerrast", "zh-hans": "不知归", "ja": "不知帰"},
    "Ночной факел": {"ru": "Ночной факел", "en": "Umbral Torch", "de": "Schattenfackel", "zh-hans": "黯色火炬", "ja": "ダークトーチ"},
    "Опус травления": {"ru": "Опус травления", "en": "Opus: Etch Figure", "de": "Opus: Atzfigur", "zh-hans": "作品：蚀迹", "ja": "作品・蝕跡"},
    "Растерзанный принц": {"ru": "Растерзанный принц", "en": "Sundered Prince", "de": "Zerrutteter Prinz", "zh-hans": "破碎君王", "ja": "破砕君主"},
    "Реактивная пика": {"ru": "Реактивная пика", "en": "JET", "de": "JET", "zh-hans": "J.E.T.", "ja": "J.E.T."},
    "Резкий подъём": {"ru": "Резкий подъём", "en": "Rapid Ascent", "de": "Schneller Aufstieg", "zh-hans": "扶摇", "ja": "フーヤオ"},
    "Рыцарская добродетель": {"ru": "Рыцарская добродетель", "en": "Chivalric Virtues", "de": "Ritterliche Tugenden", "zh-hans": "骑士精神", "ja": "騎士精神"},
    "Термитный резак": {"ru": "Термитный резак", "en": "Thermite Cutter", "de": "Thermitschneider", "zh-hans": "热熔切割器", "ja": "テルミット・カッター"},
    "Хравенгер": {"ru": "Хравенгер", "en": "Khravengger", "de": "Kravenier", "zh-hans": "赫拉芬格", "ja": "クラヴェンガー"},
    "Хранитель Горы": {"ru": "Хранитель Горы", "en": "Mountain Bearer", "de": "Bergtrager", "zh-hans": "负山", "ja": "負山"},
    "Эталон": {"ru": "Эталон", "en": "Exemplar", "de": "Mustermodell", "zh-hans": "典范", "ja": "鑑"},
}


def _character_official_name(character, language):
    """Resolve localized official character name for supported interface languages."""
    icon = str(character.get("icon") or "").strip()
    names = CHARACTER_OFFICIAL_NAMES.get(icon, {})
    normalized_language = normalize_language_code(language)
    return names.get(normalized_language) or names.get("ru") or str(character.get("name") or "")


def _character_all_aliases(character):
    """Build all known aliases including official names for supported languages."""
    values = [str(character.get("name") or "").strip()]
    values.extend(str(alias or "").strip() for alias in (character.get("aliases") or []))

    names = CHARACTER_OFFICIAL_NAMES.get(str(character.get("icon") or "").strip(), {})
    values.extend(str(localized_name or "").strip() for localized_name in names.values())

    unique = []
    seen = set()
    for value in values:
        if not value or value in seen:
            continue
        seen.add(value)
        unique.append(value)
    return unique


def _weapon_localized_name(key, language):
    """Resolve localized official weapon name by catalog key."""
    names = WEAPON_OFFICIAL_NAMES.get(str(key or "").strip(), {})
    normalized_language = normalize_language_code(language)
    return names.get(normalized_language) or names.get("ru") or str(key or "")


def _weapon_all_aliases(key):
    """Build known aliases for weapon lookup from all supported language variants."""
    raw_key = str(key or "").strip()
    names = WEAPON_OFFICIAL_NAMES.get(raw_key, {})
    values = [raw_key]
    values.extend(str(localized_name or "").strip() for localized_name in names.values())
    unique = []
    seen = set()
    for value in values:
        if not value or value in seen:
            continue
        seen.add(value)
        unique.append(value)
    return unique


def _build_weapon_name_refs(language):
    """Build lightweight weapon alias map for client-side name localization."""
    refs = []
    for key in WEAPON_OFFICIAL_NAMES.keys():
        refs.append(
            {
                "name": _weapon_localized_name(key, language),
                "aliases": _weapon_all_aliases(key),
            }
        )
    return refs


def _pity_counter_until_any(rarities, reset_values):
    """Count pulls since the latest target rarity in a reverse-sorted list."""
    counter = 0
    for rarity in rarities:
        if rarity in reset_values:
            return counter
        counter += 1
    return counter


def _pity_state_with_resets(rarities, reset_values, hard_limit):
    """Return current pity counter and pulls left to hard limit."""
    current = _pity_counter_until_any(rarities, reset_values)
    to_guarantee = max(hard_limit - current, 0)
    return current, to_guarantee


def _format_ts(gacha_ts):
    """Format epoch milliseconds as local datetime string."""
    if not gacha_ts:
        return "-"
    dt = datetime.fromtimestamp(int(gacha_ts) / 1000, tz=timezone.utc).astimezone()
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def _format_obtained_date(gacha_ts, language):
    """Format obtain date for character card status."""
    if not gacha_ts:
        return _tr_lang(language, "characters.date_unknown")
    dt = datetime.fromtimestamp(int(gacha_ts) / 1000, tz=timezone.utc).astimezone()
    return dt.strftime("%d.%m.%Y")


def _normalize_character_key(value):
    """Normalize character names/aliases for robust matching."""
    cleaned = re.sub(r"[\W_]+", "", str(value or "").strip().lower(), flags=re.UNICODE)
    return cleaned


def _build_character_obtained_map(session):
    """Build first-seen timestamp map for characters from one import session."""
    obtained_map = {}
    if not session:
        return obtained_map

    pulls = session.pulls.order_by("gacha_ts", "seq_id")
    for pull in pulls:
        key = _normalize_character_key(pull.char_name)
        if key and key not in obtained_map:
            obtained_map[key] = pull.gacha_ts
    return obtained_map


def _character_lookup_keys(character):
    """Build all lookup keys for a character definition."""
    keys = {_normalize_character_key(character.get("name"))}
    for alias in _character_all_aliases(character):
        keys.add(_normalize_character_key(alias))
    icon_stem = str(character.get("icon", "")).rsplit(".", 1)[0]
    keys.add(_normalize_character_key(icon_stem))
    return {key for key in keys if key}


def _get_first_hero_ts(session):
    """Get earliest available pull timestamp in session."""
    if not session:
        return None

    first_with_ts = (
        session.pulls.exclude(gacha_ts__isnull=True)
        .order_by("gacha_ts", "seq_id")
        .values_list("gacha_ts", flat=True)
        .first()
    )
    if first_with_ts:
        return first_with_ts

    return (
        session.pulls.order_by("seq_id")
        .values_list("gacha_ts", flat=True)
        .first()
    )


def _build_history_rows(pulls, language):
    """Build dashboard table rows with pity index per pull."""
    rows = []
    chronological_pulls = list(reversed(pulls))
    pity6 = 0
    pity5 = 0
    pity4 = 0
    for pull in chronological_pulls:
        pity6 += 1
        pity5 += 1
        pity4 += 1
        guarantee = pity4
        if pull.rarity == 6:
            guarantee = pity6
            pity6 = 0
            pity5 = 0
            pity4 = 0
        elif pull.rarity == 5:
            guarantee = pity5
            pity5 = 0
            pity4 = 0
        elif pull.rarity == 4:
            guarantee = pity4
            pity4 = 0

        rows.append(
            {
                "name": pull.char_name or pull.char_id or _tr_lang(language, "characters.unknown_name"),
                "date": _format_ts(pull.gacha_ts),
                "rarity": pull.rarity,
                "guarantee": guarantee,
            }
        )
    return list(reversed(rows))


def _build_dashboard_character_icon_refs(language):
    """Build lightweight character alias map for dashboard icon/name resolution."""
    refs = []
    for character in CHARACTERS:
        icon = str(character.get("icon") or "").strip()
        if not icon:
            continue
        icon_stem = icon.rsplit(".", 1)[0]
        keys = [icon_stem, *_character_all_aliases(character)]
        localized_name = _character_official_name(character, language)
        refs.append(
            {
                "icon": icon,
                "name": localized_name,
                "keys": [str(value).strip() for value in keys if str(value).strip()],
            }
        )
    return refs


def dashboard(request):
    """Render pity dashboard shell. Client computes personal data from local/cloud storage."""
    language = get_request_language(request)
    cards = []

    for spec in DASHBOARD_POOLS:
        title = spec.get("title")
        if not title and spec.get("title_key"):
            title = _tr_lang(language, spec["title_key"])
        cards.append(
            {
                "title": title or spec.get("source_pool_type") or "Banner",
                "total": 0,
                "six_star_pity": 0,
                "six_star_left": spec["six_star_limit"],
                "six_star_limit": spec["six_star_limit"],
                "five_star_pity": 0,
                "five_star_left": spec["five_star_limit"],
                "five_star_limit": spec["five_star_limit"],
                "history_rows": [],
                "source_pool_type": spec["source_pool_type"],
                "pool_id_fallback": spec["pool_id_fallback"],
            }
        )

    return render(
        request,
        "core/dashboard.html",
        {
            "cards": cards,
            "latest_session": None,
            "character_icon_refs": _build_dashboard_character_icon_refs(language),
            "weapon_name_refs": _build_weapon_name_refs(language),
        },
    )


def characters_page(request):
    """Render character collection shell. Client computes obtained status from local/cloud storage."""
    language = get_request_language(request)
    latest_session = None
    obtained_map = {}
    first_hero_ts = None
    characters = []
    for character in CHARACTERS:
        localized_name = _character_official_name(character, language)
        element_meta = CHARACTER_ELEMENTS.get(character["element"], {})
        weapon_meta = CHARACTER_WEAPONS.get(character["weapon"], {})
        role_meta = CHARACTER_ROLES.get(character["role"], {})
        rarity = int(character.get("rarity") or 0)
        lookup_keys = _character_lookup_keys(character)
        matched_values = [obtained_map[key] for key in lookup_keys if key in obtained_map]
        is_obtained = bool(matched_values)
        matched_ts = min((value for value in matched_values if value), default=matched_values[0] if matched_values else None)

        # Endministrator badge appears only when at least one pull exists in history.
        if character.get("icon") == "Endministrator.png" and first_hero_ts:
            is_obtained = True
            matched_ts = first_hero_ts

        characters.append(
            {
                **character,
                "name": localized_name,
                "aliases": _character_all_aliases(character),
                "rarity_icon": RARITY_ICONS.get(rarity, ""),
                "element_label": _tr_lang(language, element_meta.get("label_key", "")),
                "element_icon": element_meta.get("icon", ""),
                "weapon_label": _tr_lang(language, weapon_meta.get("label_key", "")),
                "weapon_icon": weapon_meta.get("icon", ""),
                "role_label": _tr_lang(language, role_meta.get("label_key", "")),
                "role_icon": role_meta.get("icon", ""),
                "is_obtained": is_obtained,
                "obtained_date": _format_obtained_date(matched_ts, language) if is_obtained else "",
            }
        )

    return render(
        request,
        "core/characters.html",
        {
            "characters": characters,
        },
    )


def _build_weapons_catalog(language):
    """Build weapons catalog from static assets grouped by rarity folders."""
    weapons_root = Path(settings.BASE_DIR) / "static" / "img" / "weapons"
    if not weapons_root.exists():
        return []

    supported_ext = {".webp", ".png", ".jpg", ".jpeg", ".avif"}
    weapons = []
    for rarity_dir in weapons_root.iterdir():
        if not rarity_dir.is_dir():
            continue
        rarity_name = str(rarity_dir.name).strip()
        if not rarity_name.isdigit():
            continue
        rarity = int(rarity_name)
        for icon_path in rarity_dir.iterdir():
            if not icon_path.is_file() or icon_path.suffix.lower() not in supported_ext:
                continue
            weapons.append(
                {
                    "name": _weapon_localized_name(icon_path.stem, language),
                    "icon": icon_path.name,
                    "rarity": rarity,
                }
            )

    weapons.sort(key=lambda value: (-int(value.get("rarity") or 0), str(value.get("name") or "").lower()))
    return weapons


def weapons_page(request):
    """Render weapons catalog page built from local static icons."""
    language = get_request_language(request)
    return render(
        request,
        "core/weapons.html",
        {
            "weapons": _build_weapons_catalog(language),
        },
    )


def _to_int(value, default=0):
    """Convert value to int with safe fallback."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _to_bool(value):
    """Convert mixed value types to bool."""
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y"}
    return bool(value)


def _history_export_payload():
    """Build canonical export payload from in-memory import sessions."""
    sessions = _all_import_sessions()
    return {
        "schema_version": 1,
        "exported_at": datetime.now(tz=timezone.utc).isoformat(),
        "session_count": len(sessions),
        "pull_count": sum(len((session or {}).get("pulls") or []) for session in sessions),
        "sessions": [_serialize_session(session) for session in sessions],
    }


def _is_sync_provider(provider):
    """Check whether provider supports OAuth folder sync."""
    normalized = (provider or "").strip().lower()
    return any(value == normalized for value, _label in SYNC_PROVIDER_CHOICES)


def _provider_label(provider):
    """Resolve provider display label by code."""
    normalized = (provider or "").strip().lower()
    for value, label in SYNC_PROVIDER_CHOICES:
        if value == normalized:
            return label
    for value, label in CLOUD_PROVIDER_CHOICES:
        if value == normalized:
            return label
    return normalized or "Cloud"


def _cloud_provider_credentials(provider):
    """Load OAuth client credentials for provider from settings."""
    normalized = (provider or "").strip().lower()
    if normalized == "google_drive":
        return (
            str(getattr(settings, "GOOGLE_OAUTH_CLIENT_ID", "") or "").strip(),
            str(getattr(settings, "GOOGLE_OAUTH_CLIENT_SECRET", "") or "").strip(),
        )
    if normalized == "yandex_disk":
        return (
            str(getattr(settings, "YANDEX_OAUTH_CLIENT_ID", "") or "").strip(),
            str(getattr(settings, "YANDEX_OAUTH_CLIENT_SECRET", "") or "").strip(),
        )
    return "", ""


def _cloud_provider_scope(provider):
    """Load OAuth scope configured for provider from settings."""
    normalized = (provider or "").strip().lower()
    if normalized == "google_drive":
        return str(getattr(settings, "GOOGLE_OAUTH_SCOPE", "") or "").strip()
    if normalized == "yandex_disk":
        return str(getattr(settings, "YANDEX_OAUTH_SCOPE", "") or "").strip()
    return ""


def _build_cloud_redirect_uri(request, provider):
    """Build OAuth callback URL, optionally using externally configured base URL."""
    callback_path = reverse("cloud_callback", args=[provider])
    external_base = str(getattr(settings, "DJANGO_EXTERNAL_BASE_URL", "") or "").strip().rstrip("/")
    if external_base:
        return urljoin(f"{external_base}/", callback_path.lstrip("/"))
    return request.build_absolute_uri(callback_path)


def _is_cloud_oauth_configured(provider):
    """Return True when provider has both client id and secret configured."""
    client_id, client_secret = _cloud_provider_credentials(provider)
    return bool(client_id and client_secret)


def _get_cloud_auth_map(request):
    """Read cloud auth mapping from session in normalized format."""
    data = request.session.get(CLOUD_AUTH_SESSION_KEY)
    if isinstance(data, dict):
        return data
    return {}


def _save_cloud_auth_map(request, auth_map):
    """Persist cloud auth mapping to session."""
    request.session[CLOUD_AUTH_SESSION_KEY] = auth_map
    request.session.modified = True


def _set_settings_flash(request, message, message_type="info", message_details=""):
    """Store one-time status message for settings page."""
    request.session[SETTINGS_FLASH_SESSION_KEY] = {
        "message": message,
        "message_type": message_type,
        "message_details": message_details,
    }
    request.session.modified = True


def _pop_settings_flash(request):
    """Pop one-time settings flash payload from session."""
    payload = request.session.pop(SETTINGS_FLASH_SESSION_KEY, None)
    if isinstance(payload, dict):
        return {
            "message": payload.get("message", ""),
            "message_type": payload.get("message_type", ""),
            "message_details": payload.get("message_details", ""),
        }
    return {"message": "", "message_type": "", "message_details": ""}


def _store_provider_tokens(request, provider, token_payload):
    """Persist provider OAuth token payload in session auth map."""
    normalized = (provider or "").strip().lower()
    auth_map = _get_cloud_auth_map(request)
    provider_auth = auth_map.get(normalized) if isinstance(auth_map.get(normalized), dict) else {}

    access_token = str(token_payload.get("access_token") or "").strip()
    if not access_token:
        raise CloudIntegrationError(_tr(request, "view.cloud.no_token"))

    provider_auth["access_token"] = access_token
    provider_auth["token_type"] = str(token_payload.get("token_type") or "").strip()

    refresh_token = str(token_payload.get("refresh_token") or "").strip()
    if refresh_token:
        provider_auth["refresh_token"] = refresh_token

    try:
        expires_in = int(token_payload.get("expires_in") or 0)
    except (TypeError, ValueError):
        expires_in = 0

    if expires_in > 0:
        provider_auth["expires_at"] = int(time.time()) + max(expires_in - 30, 30)
    else:
        provider_auth.pop("expires_at", None)

    auth_map[normalized] = provider_auth
    _save_cloud_auth_map(request, auth_map)


def _build_cloud_cards_context(request):
    """Build UI model for cloud cards shown in settings page."""
    auth_map = _get_cloud_auth_map(request)
    now_ts = int(time.time())
    cards = []
    for provider, label in SYNC_PROVIDER_CHOICES:
        auth = auth_map.get(provider) if isinstance(auth_map.get(provider), dict) else {}
        access_token = str(auth.get("access_token") or "").strip()
        expires_at_raw = auth.get("expires_at")
        try:
            expires_at = int(expires_at_raw or 0)
        except (TypeError, ValueError):
            expires_at = 0

        cards.append(
            {
                "provider": provider,
                "label": label,
                "configured": _is_cloud_oauth_configured(provider),
                "connected": bool(access_token),
                "token_expiring": bool(expires_at and expires_at <= now_ts + 60),
                "setup_hint": (
                    "GOOGLE_OAUTH_CLIENT_ID, GOOGLE_OAUTH_CLIENT_SECRET, GOOGLE_OAUTH_SCOPE"
                    if provider == "google_drive"
                    else "YANDEX_OAUTH_CLIENT_ID, YANDEX_OAUTH_CLIENT_SECRET, YANDEX_OAUTH_SCOPE"
                ),
            }
        )
    return cards


def _ensure_cloud_access_token(request, provider):
    """Return valid access token, refreshing it if needed."""
    normalized = (provider or "").strip().lower()
    if not _is_sync_provider(normalized):
        raise CloudIntegrationError(_tr(request, "view.cloud.unknown_provider"))

    if not _is_cloud_oauth_configured(normalized):
        label = _provider_label(normalized)
        raise CloudIntegrationError(_tr(request, "view.cloud.server_not_configured", provider=label))

    auth_map = _get_cloud_auth_map(request)
    auth = auth_map.get(normalized) if isinstance(auth_map.get(normalized), dict) else {}
    access_token = str(auth.get("access_token") or "").strip()
    refresh_token = str(auth.get("refresh_token") or "").strip()

    if not access_token:
        raise CloudIntegrationError(_tr(request, "view.cloud.connect_first", provider=_provider_label(normalized)))

    expires_at_raw = auth.get("expires_at")
    try:
        expires_at = int(expires_at_raw or 0)
    except (TypeError, ValueError):
        expires_at = 0

    if expires_at and expires_at <= int(time.time()) + 30:
        client_id, client_secret = _cloud_provider_credentials(normalized)
        refreshed = refresh_oauth_token(
            provider=normalized,
            client_id=client_id,
            client_secret=client_secret,
            refresh_token=refresh_token,
        )
        _store_provider_tokens(request, normalized, refreshed)
        return str(refreshed.get("access_token") or "").strip()

    return access_token


def _settings_context(request, message="", message_type="", message_details=""):
    """Build settings page context with cloud connection status."""
    donate_url = getattr(settings, "DONATE_URL", DEFAULT_DONATE_URL)
    repository_url = getattr(settings, "OFFICIAL_REPOSITORY_URL", OFFICIAL_REPOSITORY_URL)
    return {
        "status_message": message,
        "status_message_type": message_type,
        "status_message_details": message_details,
        "donate_url": donate_url,
        "repository_url": repository_url,
        "cloud_cards": _build_cloud_cards_context(request),
        "cloud_folder_name": SYNC_FOLDER_NAME,
        "cloud_file_name": SYNC_FILE_NAME,
    }


def _render_settings(request, message="", message_type="", message_details=""):
    """Render settings page with optional status alert."""
    return render(
        request,
        "core/settings.html",
        _settings_context(
            request=request,
            message=message,
            message_type=message_type,
            message_details=message_details,
        ),
    )


def settings_page(request):
    """Render settings page with optional flash message."""
    flash = _pop_settings_flash(request)
    return _render_settings(
        request,
        message=flash.get("message", ""),
        message_type=flash.get("message_type", ""),
        message_details=flash.get("message_details", ""),
    )


def set_site_language(request):
    """Update interface language and redirect back to previous page."""
    if request.method != "POST":
        return HttpResponseBadRequest("POST only")

    lang = normalize_language_code(request.POST.get("lang"))
    next_url = (request.POST.get("next") or "").strip() or reverse("dashboard")
    if not url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
        next_url = reverse("dashboard")

    request.session[SITE_LANGUAGE_SESSION_KEY] = lang
    request.site_language = lang
    response = redirect(next_url)
    response.set_cookie(SITE_LANGUAGE_COOKIE_KEY, lang, max_age=60 * 60 * 24 * 365, samesite="Lax")
    return response


def privacy_policy(request):
    """Render privacy policy page."""
    return render(request, "core/privacy_policy.html")


def cookies_policy(request):
    """Render cookie policy page."""
    return render(request, "core/cookies_policy.html")


def _serialize_session(session):
    """Serialize in-memory import session with pulls to export JSON."""
    pulls = list((session or {}).get("pulls") or [])
    return {
        "source_session_id": (session or {}).get("id"),
        "created_at": (session or {}).get("created_at"),
        "server_id": (session or {}).get("server_id"),
        "lang": (session or {}).get("lang"),
        "status": (session or {}).get("status"),
        "error": (session or {}).get("error"),
        "pulls": pulls,
    }


def export_history(request):
    """Download full local history as JSON attachment."""
    payload = _history_export_payload()
    response = JsonResponse(payload, json_dumps_params={"ensure_ascii": False, "indent": 2})
    timestamp = datetime.now(tz=timezone.utc).strftime("%Y%m%d-%H%M%S")
    response["Content-Disposition"] = f'attachment; filename="endfieldpass-history-{timestamp}.json"'
    return response


def _build_session_payloads(payload):
    """Support both new schema (sessions) and legacy (items)."""
    sessions = payload.get("sessions")
    if isinstance(sessions, list):
        return sessions

    items = payload.get("items")
    if isinstance(items, list):
        return [
            {
                "server_id": payload.get("server_id") or "3",
                "lang": payload.get("lang") or "ru-ru",
                "status": "done",
                "pulls": items,
            }
        ]
    return None


def _import_history_payload(payload):
    """Validate history payload shape and return counters without writing DB."""
    if not isinstance(payload, dict):
        raise ValueError("view.error.bad_payload")

    sessions_payload = _build_session_payloads(payload)
    if sessions_payload is None:
        raise ValueError("view.error.bad_format")

    imported_sessions = 0
    imported_pulls = 0
    for session_payload in sessions_payload:
        if not isinstance(session_payload, dict):
            continue
        imported_sessions += 1
        pulls_payload = session_payload.get("pulls")
        if not isinstance(pulls_payload, list):
            pulls_payload = session_payload.get("items")
        if isinstance(pulls_payload, list):
            imported_pulls += sum(1 for item in pulls_payload if isinstance(item, dict))

    return imported_sessions, imported_pulls


def import_history(request):
    """Import local history from uploaded JSON file."""
    if request.method != "POST":
        return HttpResponseBadRequest("POST only")

    uploaded_file = request.FILES.get("history_file")
    if not uploaded_file:
        return _render_settings(request, _tr(request, "view.settings.select_json"), "error")

    try:
        raw_payload = uploaded_file.read().decode("utf-8")
        payload = json.loads(raw_payload)
        imported_sessions, imported_pulls = _import_history_payload(payload)
    except UnicodeDecodeError:
        return _render_settings(request, _tr(request, "view.settings.utf8"), "error")
    except json.JSONDecodeError:
        return _render_settings(request, _tr(request, "view.settings.read_json"), "error")
    except ValueError as exc:
        return _render_settings(request, _tr(request, "view.settings.import_failed"), "error", _tr(request, str(exc)))
    except Exception as exc:
        return _render_settings(request, _tr(request, "view.settings.import_error"), "error", str(exc))

    details = _tr(request, "view.settings.counts", sessions=imported_sessions, pulls=imported_pulls)
    return _render_settings(request, _tr(request, "view.settings.import_done"), "success", details)


def cloud_connect(request, provider):
    """Start provider OAuth connection flow."""
    normalized = (provider or "").strip().lower()
    if not _is_sync_provider(normalized):
        return HttpResponseBadRequest("unknown provider")

    if not _is_cloud_oauth_configured(normalized):
        label = _provider_label(normalized)
        return _render_settings(
            request,
            _tr(request, "view.cloud.provider_not_configured", provider=label),
            "error",
            _tr(request, "view.cloud.provider_not_configured_details"),
        )

    client_id, _client_secret = _cloud_provider_credentials(normalized)
    state = secrets.token_urlsafe(24)
    request.session[CLOUD_OAUTH_STATE_SESSION_KEY] = {"provider": normalized, "state": state}
    request.session.modified = True

    redirect_uri = _build_cloud_redirect_uri(request, normalized)
    try:
        auth_url = build_oauth_authorization_url(
            provider=normalized,
            client_id=client_id,
            redirect_uri=redirect_uri,
            state=state,
            scope=_cloud_provider_scope(normalized),
        )
    except CloudIntegrationError as exc:
        return _render_settings(request, _tr(request, "view.cloud.oauth_start_failed"), "error", str(exc))

    return redirect(auth_url)


def cloud_callback(request, provider):
    """Handle provider OAuth callback and store tokens."""
    normalized = (provider or "").strip().lower()
    if not _is_sync_provider(normalized):
        return HttpResponseBadRequest("unknown provider")

    oauth_state = request.session.pop(CLOUD_OAUTH_STATE_SESSION_KEY, None)
    expected_provider = oauth_state.get("provider") if isinstance(oauth_state, dict) else ""
    expected_state = oauth_state.get("state") if isinstance(oauth_state, dict) else ""
    received_state = (request.GET.get("state") or "").strip()
    code = (request.GET.get("code") or "").strip()
    provider_error = (request.GET.get("error_description") or request.GET.get("error") or "").strip()

    if provider_error:
        _set_settings_flash(
            request,
            _tr(request, "view.cloud.oauth_denied", provider=_provider_label(normalized)),
            "error",
            provider_error,
        )
        return redirect("settings_page")

    if not expected_provider or expected_provider != normalized or not expected_state or expected_state != received_state:
        _set_settings_flash(
            request,
            _tr(request, "view.cloud.oauth_state_failed"),
            "error",
            _tr(request, "view.cloud.oauth_state_details"),
        )
        return redirect("settings_page")

    if not code:
        _set_settings_flash(
            request,
            _tr(request, "view.cloud.oauth_code_missing"),
            "error",
            _tr(request, "view.cloud.oauth_code_missing_details"),
        )
        return redirect("settings_page")

    client_id, client_secret = _cloud_provider_credentials(normalized)
    redirect_uri = _build_cloud_redirect_uri(request, normalized)
    try:
        token_payload = exchange_oauth_code(
            provider=normalized,
            client_id=client_id,
            client_secret=client_secret,
            redirect_uri=redirect_uri,
            code=code,
        )
        _store_provider_tokens(request, normalized, token_payload)
    except CloudIntegrationError as exc:
        _set_settings_flash(
            request,
            _tr(request, "view.cloud.oauth_connect_failed", provider=_provider_label(normalized)),
            "error",
            str(exc),
        )
        return redirect("settings_page")

    _set_settings_flash(
        request,
        _tr(request, "view.cloud.oauth_connected", provider=_provider_label(normalized)),
        "success",
        _tr(request, "view.cloud.oauth_connected_details"),
    )
    return redirect("settings_page")


def cloud_disconnect(request, provider):
    """Disconnect cloud provider for current user session."""
    if request.method != "POST":
        return HttpResponseBadRequest("POST only")

    normalized = (provider or "").strip().lower()
    if not _is_sync_provider(normalized):
        return HttpResponseBadRequest("unknown provider")

    auth_map = _get_cloud_auth_map(request)
    auth_map.pop(normalized, None)
    _save_cloud_auth_map(request, auth_map)
    _set_settings_flash(request, _tr(request, "view.cloud.oauth_disconnected", provider=_provider_label(normalized)), "success")
    return redirect("settings_page")


def cloud_export(request):
    """Sync local history payload to connected cloud provider."""
    if request.method != "POST":
        return HttpResponseBadRequest("POST only")

    provider = (request.POST.get("provider") or "").strip().lower()
    if not _is_sync_provider(provider):
        return _render_settings(request, _tr(request, "view.cloud.choose_sync_provider"), "error")

    try:
        access_token = _ensure_cloud_access_token(request, provider)
        payload = _history_export_payload()
        result = export_payload_to_cloud(
            provider=provider,
            token=access_token,
            payload=payload,
        )
    except CloudIntegrationError as exc:
        return _render_settings(request, _tr(request, "view.cloud.sync_failed"), "error", str(exc))
    except Exception as exc:
        return _render_settings(request, _tr(request, "view.cloud.sync_error"), "error", str(exc))

    if provider == "google_drive":
        details = _tr(
            request,
            "view.cloud.sync_done_google",
            folder=result.get("folder_name") or SYNC_FOLDER_NAME,
            file=result.get("file_name") or SYNC_FILE_NAME,
        )
    else:
        details = _tr(request, "view.cloud.sync_done_yandex", path=result.get("path") or f"app:/{SYNC_FOLDER_NAME}/{SYNC_FILE_NAME}")
    return _render_settings(request, _tr(request, "view.cloud.sync_done"), "success", details)


def cloud_import(request):
    """Import history payload from connected cloud provider or URL."""
    if request.method != "POST":
        return HttpResponseBadRequest("POST only")

    provider = (request.POST.get("provider") or "").strip().lower()
    remote_ref = (request.POST.get("remote_ref") or "").strip()
    if not provider:
        return _render_settings(request, _tr(request, "view.cloud.choose_import_source"), "error")

    try:
        if provider == "url":
            if not remote_ref:
                return _render_settings(request, _tr(request, "view.cloud.url_required"), "error")
            payload = import_payload_from_cloud(provider="url", token="", remote_ref=remote_ref)
        else:
            access_token = _ensure_cloud_access_token(request, provider)
            payload = import_payload_from_cloud(provider=provider, token=access_token, remote_ref="")

        imported_sessions, imported_pulls = _import_history_payload(payload)
    except CloudIntegrationError as exc:
        return _render_settings(request, _tr(request, "view.cloud.import_failed"), "error", str(exc))
    except ValueError as exc:
        return _render_settings(request, _tr(request, "view.cloud.import_bad_format"), "error", _tr(request, str(exc)))
    except Exception as exc:
        return _render_settings(request, _tr(request, "view.cloud.import_error"), "error", str(exc))

    details = _tr(request, "view.settings.counts", sessions=imported_sessions, pulls=imported_pulls)
    return _render_settings(request, _tr(request, "view.cloud.import_done"), "success", details)


def _parse_json_body(request):
    """Parse request body as JSON object."""
    try:
        payload = json.loads(request.body.decode("utf-8"))
    except Exception:
        return None
    return payload if isinstance(payload, dict) else None


def _connected_sync_providers(request):
    """Return list of connected OAuth sync providers."""
    providers = []
    auth_map = _get_cloud_auth_map(request)
    for provider, _label in SYNC_PROVIDER_CHOICES:
        auth = auth_map.get(provider) if isinstance(auth_map.get(provider), dict) else {}
        if str(auth.get("access_token") or "").strip():
            providers.append(provider)
    return providers


@csrf_exempt
def cloud_connected_providers_api(request):
    """Return connected cloud providers for automatic client-side sync."""
    if request.method != "GET":
        return HttpResponseBadRequest("GET only")
    return JsonResponse({"providers": _connected_sync_providers(request)})


@csrf_exempt
def cloud_auto_import_api(request):
    """Fetch cloud JSON payload and return it to client without DB writes."""
    if request.method != "POST":
        return HttpResponseBadRequest("POST only")

    body = _parse_json_body(request)
    if body is None:
        return HttpResponseBadRequest("bad json")

    provider = str(body.get("provider") or "").strip().lower()
    remote_ref = str(body.get("remote_ref") or "").strip()
    if provider != "url" and not _is_sync_provider(provider):
        return JsonResponse({"ok": False, "error": _tr(request, "view.cloud.choose_sync_provider")}, status=400)

    try:
        if provider == "url":
            if not remote_ref:
                return JsonResponse({"ok": False, "error": _tr(request, "view.cloud.url_required")}, status=400)
            payload = import_payload_from_cloud(provider="url", token="", remote_ref=remote_ref)
        else:
            access_token = _ensure_cloud_access_token(request, provider)
            payload = import_payload_from_cloud(provider=provider, token=access_token, remote_ref="")
        imported_sessions, imported_pulls = _import_history_payload(payload)
        return JsonResponse(
            {
                "ok": True,
                "provider": provider,
                "payload": payload,
                "session_count": imported_sessions,
                "pull_count": imported_pulls,
            }
        )
    except CloudIntegrationError as exc:
        return JsonResponse({"ok": False, "error": str(exc)}, status=400)
    except ValueError as exc:
        return JsonResponse({"ok": False, "error": _tr(request, str(exc))}, status=400)
    except Exception as exc:
        return JsonResponse({"ok": False, "error": str(exc)}, status=500)


@csrf_exempt
def cloud_auto_export_api(request):
    """Push client-provided JSON payload to connected cloud provider."""
    if request.method != "POST":
        return HttpResponseBadRequest("POST only")

    body = _parse_json_body(request)
    if body is None:
        return HttpResponseBadRequest("bad json")

    provider = str(body.get("provider") or "").strip().lower()
    payload = body.get("payload")
    if not _is_sync_provider(provider):
        return JsonResponse({"ok": False, "error": _tr(request, "view.cloud.choose_sync_provider")}, status=400)
    if not isinstance(payload, dict):
        return JsonResponse({"ok": False, "error": _tr(request, "view.error.bad_payload")}, status=400)

    try:
        access_token = _ensure_cloud_access_token(request, provider)
        result = export_payload_to_cloud(provider=provider, token=access_token, payload=payload)
        return JsonResponse({"ok": True, "provider": provider, "result": result})
    except CloudIntegrationError as exc:
        return JsonResponse({"ok": False, "error": str(exc)}, status=400)
    except Exception as exc:
        return JsonResponse({"ok": False, "error": str(exc)}, status=500)


def _default_form_data():
    """Return default import form values."""
    return {
        "page_url": "",
        "token": "",
        "server_id": "3",
        "lang": "ru-ru",
    }


def _set_progress(session_id: int, *, status=None, progress=None, message=None, error=None):
    """Update in-memory progress state for async import session."""
    with IMPORT_PROGRESS_LOCK:
        state = IMPORT_PROGRESS.get(session_id, {})
        if status is not None:
            state["status"] = status
        if progress is not None:
            state["progress"] = max(0, min(100, int(progress)))
        if message is not None:
            state["message"] = message
        if error is not None:
            state["error"] = error
        IMPORT_PROGRESS[session_id] = state


def _get_progress(session_id: int):
    """Read in-memory progress state for async import session."""
    with IMPORT_PROGRESS_LOCK:
        state = IMPORT_PROGRESS.get(session_id, {})
        return {
            "status": state.get("status"),
            "progress": state.get("progress"),
            "message": state.get("message"),
            "error": state.get("error", ""),
        }


def _next_import_session_id():
    """Generate process-local import session id."""
    global IMPORT_SESSION_COUNTER
    with IMPORT_PROGRESS_LOCK:
        IMPORT_SESSION_COUNTER += 1
        return IMPORT_SESSION_COUNTER


def _set_import_session(session_id: int, **updates):
    """Upsert in-memory import session payload."""
    with IMPORT_PROGRESS_LOCK:
        session = IMPORT_SESSIONS.get(session_id, {})
        session.update(updates)
        IMPORT_SESSIONS[session_id] = session
        return deepcopy(session)


def _get_import_session(session_id: int):
    """Read in-memory import session payload."""
    with IMPORT_PROGRESS_LOCK:
        session = IMPORT_SESSIONS.get(session_id)
        return deepcopy(session) if session else None


def _all_import_sessions():
    """Return all in-memory import sessions sorted by created_at desc."""
    with IMPORT_PROGRESS_LOCK:
        sessions = [deepcopy(value) for value in IMPORT_SESSIONS.values()]
    return sorted(sessions, key=lambda value: str(value.get("created_at") or ""), reverse=True)


def _latest_import_session():
    """Return latest in-memory import session."""
    sessions = _all_import_sessions()
    return sessions[0] if sessions else None


def _normalize_pull_item(item):
    """Normalize one pull record to canonical export format."""
    pool_id = str(item.get("pool_id") or item.get("poolId") or "UNKNOWN")
    source_pool_type = str(item.get("source_pool_type") or item.get("_source_pool_type") or "")
    weapon_id = str(item.get("weapon_id") or item.get("weaponId") or "")
    weapon_name = str(item.get("weapon_name") or item.get("weaponName") or "")
    char_id = str(item.get("char_id") or item.get("charId") or weapon_id)
    char_name = str(item.get("char_name") or item.get("charName") or weapon_name)

    raw_item_type = str(item.get("item_type") or item.get("itemType") or "").strip().lower()
    source_hint = source_pool_type.lower()
    pool_hint = pool_id.lower()
    inferred_item_type = raw_item_type
    if inferred_item_type not in {"character", "weapon"}:
        if weapon_id or weapon_name or "weapon" in source_hint or "wepon" in pool_hint or "weapon" in pool_hint:
            inferred_item_type = "weapon"
        else:
            inferred_item_type = "character"

    return {
        "pool_id": pool_id,
        "pool_name": str(item.get("pool_name") or item.get("poolName") or ""),
        "char_id": char_id,
        "char_name": char_name,
        "rarity": _to_int(item.get("rarity"), default=0),
        "is_free": _to_bool(item.get("is_free") if "is_free" in item else item.get("isFree")),
        "is_new": _to_bool(item.get("is_new") if "is_new" in item else item.get("isNew")),
        "gacha_ts": _to_int(item.get("gacha_ts") if "gacha_ts" in item else item.get("gachaTs"), default=0) or None,
        "seq_id": _to_int(item.get("seq_id") if "seq_id" in item else item.get("seqId"), default=0),
        "source_pool_type": source_pool_type,
        "item_type": inferred_item_type,
        "weapon_id": weapon_id,
        "weapon_name": weapon_name,
    }


def _parse_page_url_details(page_url: str):
    """Parse token/server/lang/import_kind/pool_id from game history URL."""
    if not page_url:
        return {
            "token": "",
            "server_id": "",
            "lang": "ru-ru",
            "import_kind": "character",
            "pool_id": "",
        }

    parsed = urlparse(page_url)
    query = parse_qs(parsed.query)
    path = str(parsed.path or "").lower()

    import_kind = "weapon" if "gacha_weapon" in path else "character"
    token = str((query.get("u8_token") or query.get("token") or [""])[0] or "")
    server_id = str((query.get("server") or query.get("server_id") or [""])[0] or "")
    lang = str((query.get("lang") or ["ru-ru"])[0] or "ru-ru")
    pool_id = str((query.get("pool_id") or [""])[0] or "")
    return {
        "token": token,
        "server_id": server_id,
        "lang": lang,
        "import_kind": import_kind,
        "pool_id": pool_id,
    }


def _run_import_session(session_id: int, ui_language: str):
    """Background job: fetch pulls and keep them in process memory only."""
    session = _get_import_session(session_id)
    if not session:
        return
    _set_progress(session_id, status="running", progress=3, message=_tr_lang(ui_language, "import.loading.prepare"))

    def resolve_pool_label(pool_type, **kwargs):
        pool_label_key = POOL_LABELS.get(pool_type)
        if pool_label_key:
            return _tr_lang(ui_language, pool_label_key)
        pool_label = str(kwargs.get("pool_name") or kwargs.get("pool_id") or pool_type or "").strip()
        if pool_label:
            return pool_label
        if "weapon" in str(pool_type or "").lower():
            return _tr_lang(ui_language, "dashboard.pool.weapon")
        return _tr_lang(ui_language, "dashboard.pool.generic")

    def on_character_pool_progress(index, total, pool_type, stage, **kwargs):
        safe_total = max(int(total or 1), 1)
        pool_label = resolve_pool_label(pool_type, **kwargs)
        if stage == "start":
            progress = 5 + int(((index - 1) / safe_total) * 55)
            message = f"{_tr_lang(ui_language, 'import.loading.hint1')} {pool_label}."
        else:
            progress = 5 + int((index / safe_total) * 55)
            message = _tr_lang(ui_language, "import.loading.hint2")
        _set_progress(session_id, status="running", progress=progress, message=message)

    def on_weapon_pool_progress(index, total, pool_type, stage, **kwargs):
        safe_total = max(int(total or 1), 1)
        pool_label = resolve_pool_label(pool_type, **kwargs)
        if stage == "start":
            progress = 65 + int(((index - 1) / safe_total) * 25)
            message = f"{_tr_lang(ui_language, 'import.loading.hint1')} {pool_label}."
        else:
            progress = 65 + int((index / safe_total) * 25)
            message = _tr_lang(ui_language, "import.loading.hint2")
        _set_progress(session_id, status="running", progress=progress, message=message)

    try:
        token = str(session.get("token") or "")
        server_id = str(session.get("server_id") or "")
        lang = str(session.get("lang") or "ru-ru")
        selected_pool_id = str(session.get("selected_pool_id") or "")

        # Import both sources in one pass: character + weapon.
        character_items = fetch_all_records(
            token=token,
            server_id=server_id,
            lang=lang,
            import_kind="character",
            on_pool_progress=on_character_pool_progress,
        )
        weapon_items = fetch_all_records(
            token=token,
            server_id=server_id,
            lang=lang,
            import_kind="weapon",
            selected_pool_id=selected_pool_id,
            on_pool_progress=on_weapon_pool_progress,
        )
        items = [*character_items, *weapon_items]

        pulls = []
        seen = set()
        for item in items:
            normalized = _normalize_pull_item(item)
            seq_id = _to_int(normalized.get("seq_id"), default=0)
            pool_id = str(normalized.get("pool_id") or "").strip()
            dedupe_key = f"{pool_id}:{seq_id}" if pool_id and seq_id else ""
            if dedupe_key and dedupe_key in seen:
                continue
            if dedupe_key:
                seen.add(dedupe_key)
            pulls.append(normalized)
        pulls.sort(
            key=lambda value: (
                _to_int(value.get("gacha_ts"), default=0),
                _to_int(value.get("seq_id"), default=0),
            ),
            reverse=True,
        )

        _set_progress(
            session_id,
            status="running",
            progress=92,
            message=_tr_lang(ui_language, "import.loading.hint3"),
        )

        total = len(pulls)
        if total:
            _set_progress(
                session_id,
                status="running",
                progress=99,
                message=f"{_tr_lang(ui_language, 'import.error.processing')} {total}/{total}.",
            )

        _set_import_session(
            session_id,
            status="done",
            error="",
            pulls=pulls,
        )
        _set_progress(session_id, status="done", progress=100, message=_tr_lang(ui_language, "view.settings.import_done"))
    except Exception as exc:
        _set_import_session(
            session_id,
            status="error",
            error=str(exc),
            pulls=[],
        )
        _set_progress(
            session_id,
            status="error",
            progress=100,
            message=_tr_lang(ui_language, "view.settings.import_error"),
            error=str(exc),
        )


def import_page(request):
    """Render import page with empty/default state."""
    return render(
        request,
        "endfield_tracker/import_view.html",
        {
            "error": "",
            "form": _default_form_data(),
            "session": None,
            "pulls": [],
        },
    )


@csrf_exempt
def create_session(request):
    """Create async import session and start background worker thread."""
    if request.method != "POST":
        return HttpResponseBadRequest("POST only")

    try:
        payload = json.loads(request.body.decode("utf-8"))
    except Exception:
        return HttpResponseBadRequest("bad json")

    token = (payload.get("token") or "").strip()
    server_id = str(payload.get("server_id") or "").strip()
    page_url = (payload.get("page_url") or "").strip()
    lang = (payload.get("lang") or "ru-ru").strip()
    import_kind = str(payload.get("import_kind") or "").strip().lower()
    selected_pool_id = ""
    parsed_url = _parse_page_url_details(page_url) if page_url else {}

    if page_url:
        if not import_kind:
            import_kind = str(parsed_url.get("import_kind") or "character").strip().lower()
        selected_pool_id = str(parsed_url.get("pool_id") or "").strip()

    if page_url and (not token or not server_id):
        token = token or parsed_url.get("token", "")
        server_id = server_id or parsed_url.get("server_id", "")
        if not payload.get("lang"):
            lang = parsed_url.get("lang", "ru-ru")

    if import_kind not in {"character", "weapon"}:
        import_kind = "character"

    if not token or not server_id:
        return HttpResponseBadRequest("missing token/server_id")

    session_id = _next_import_session_id()
    session = _set_import_session(
        session_id,
        id=session_id,
        created_at=datetime.now(tz=timezone.utc).isoformat(),
        token=token,
        server_id=server_id,
        lang=lang,
        page_url=page_url,
        import_kind=import_kind,
        selected_pool_id=selected_pool_id,
        status="running",
        error="",
        pulls=[],
    )
    ui_language = get_request_language(request)
    _set_progress(session_id, status="running", progress=1, message=_tr_lang(ui_language, "import.loading.prepare"))

    thread = threading.Thread(target=_run_import_session, args=(session_id, ui_language), daemon=True)
    thread.start()

    return JsonResponse({"session_id": session_id, "status": session.get("status")})


def import_status(request, session_id: int):
    """Return current import progress and status as JSON."""
    session = _get_import_session(session_id)
    if not session:
        return JsonResponse({"error": "invalid session"}, status=404)
    progress_state = _get_progress(session_id)

    progress = progress_state.get("progress")
    if progress is None:
        progress = 100 if session.get("status") in {"done", "error"} else 0

    if session.get("status") == "done":
        progress = 100
    message = progress_state.get("message") or _tr(request, "import.error.processing")

    return JsonResponse(
        {
            "session_id": session_id,
            "status": session.get("status") or "running",
            "progress": progress,
            "message": message,
            "error": session.get("error") or "",
            "pull_count": len(session.get("pulls") or []),
        }
    )


def import_view(request, session_id: int):
    """Render import page with a specific session result preview."""
    session = _get_import_session(session_id)
    if not session:
        return render(
            request,
            "endfield_tracker/import_view.html",
            {
                "session": None,
                "pulls": [],
                "error": _tr(request, "import.error.invalid_session"),
                "form": _default_form_data(),
            },
        )
    pulls = list((session.get("pulls") or [])[:500])
    return render(
        request,
        "endfield_tracker/import_view.html",
        {
            "session": session,
            "pulls": pulls,
            "error": "",
            "form": {
                "page_url": session.get("page_url", ""),
                "token": session.get("token", ""),
                "server_id": session.get("server_id", "3"),
                "lang": session.get("lang", "ru-ru"),
            },
        },
    )


def pulls_json(request, session_id: int):
    """Return pulls JSON for a single import session."""
    session = _get_import_session(session_id)
    if not session:
        return JsonResponse({"error": "invalid session"}, status=404)
    items = list(session.get("pulls") or [])
    return JsonResponse(
        {
            "session_id": session_id,
            "count": len(items),
            "items": items,
        }
    )


def pulls_api(request):
    """Return pulls JSON with optional session/pool filters."""
    session_id = (request.GET.get("session_id") or "").strip()
    pool_id = (request.GET.get("pool_id") or "").strip()
    limit_raw = (request.GET.get("limit") or "5000").strip()

    try:
        limit = int(limit_raw)
    except ValueError:
        limit = 5000
    limit = max(1, min(limit, 5000))

    if session_id:
        try:
            parsed_session_id = int(session_id)
        except ValueError:
            return JsonResponse({"error": "invalid session_id"}, status=400)
        session = _get_import_session(parsed_session_id)
    else:
        session = _latest_import_session()
    if not session:
        return JsonResponse({"session_id": None, "count": 0, "items": []})

    items = list(session.get("pulls") or [])
    items.sort(key=lambda value: _to_int(value.get("seq_id"), default=0), reverse=True)
    if pool_id:
        items = [item for item in items if str(item.get("pool_id") or "") == pool_id]
    return JsonResponse(
        {
            "session_id": session.get("id"),
            "pool_id": pool_id or None,
            "count": len(items),
            "items": items[:limit],
        }
    )
