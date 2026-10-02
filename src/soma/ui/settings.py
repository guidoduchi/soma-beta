"""Presentation values; LLD-02 alone owns setting persistence/mutations."""
import json
from importlib.resources import files
from soma.foundation.errors import ValidationError
from soma.reference.domain.settings import SettingDefinition, SettingDefinitionRegistry


def build_ui_setting_registry():
    registry = SettingDefinitionRegistry()
    definitions = json.loads(files('soma.ui').joinpath('registry.json').read_text(encoding='utf8'))['leaves']['settings/presentation.json']['settings']
    for item in definitions:
        def validate(value, allowed=frozenset(item['value_contract']['values'])):
            if not isinstance(value, str) or value not in allowed:
                raise ValidationError('UI presentation setting is not a registered value')
            return value
        registry.register(SettingDefinition(item['key'], 'LLD-10', item['key'] + '.v1', 1,
            lambda value=item['default']: value, validate, lambda left, right: type(left) is type(right) and left == right))
    return registry
