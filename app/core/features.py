from enum import Enum
from typing import Iterable


class Feature(str, Enum):
    phones = "phones"
    templates = "templates"
    campaigns = "campaigns"
    storage = "storage"
    calls = "calls"
    auto_reply = "auto_reply"
    messages = "messages"
    blacklist = "blacklist"
    train = "train"
    settings = "settings"
    chat = "chat"
    flows = "flows"
    tickets = "tickets"


FEATURE_DEPENDENCIES: dict[Feature, tuple[Feature, ...]] = {
    Feature.messages: (Feature.phones,),
    Feature.campaigns: (Feature.phones, Feature.templates),
    Feature.calls: (Feature.phones, Feature.templates),
    Feature.auto_reply: (Feature.phones,),
    Feature.train: (Feature.phones,),
    Feature.chat: (Feature.phones, Feature.messages),
    Feature.flows: (Feature.phones,),
}


def normalize_feature(value: Feature | str) -> Feature:
    return value if isinstance(value, Feature) else Feature(str(value))


def expand_features(features: Iterable[Feature | str]) -> list[Feature]:
    ordered: list[Feature] = []
    seen: set[Feature] = set()

    def visit(feature_value: Feature | str):
        feature = normalize_feature(feature_value)
        if feature in seen:
            return

        for dependency in FEATURE_DEPENDENCIES.get(feature, ()):
            visit(dependency)

        seen.add(feature)
        ordered.append(feature)

    for item in features:
        visit(item)

    return ordered
