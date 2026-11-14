"""Golden protobuf bytes for the firmware's ESPHome API codec (tests/fixtures/esphome_api/*.hex).

Uses aioesphomeapi's api_pb2 when it is installed (pip install aioesphomeapi in a separate venv). Without it, the
messages are built with google.protobuf from descriptors that copy the field numbers of esphome's api.proto
(esphome/components/api/api.proto, dev branch, checked 2026-11), so a real protobuf implementation still makes
the bytes. Run: python tools/gen_api_fixtures.py   (docs/design/esphome.md, B.1 and B.8)
"""
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / 'tests' / 'fixtures' / 'esphome_api'


def fnv1(text):
    value = 2166136261
    for byte in text.encode():
        value = (value * 16777619) & 0xFFFFFFFF
        value ^= byte
    return value


# (message, [(name, number, type, repeated)]) with types from descriptor_pb2.FieldDescriptorProto.
FIELDS = {
    'HelloRequest': [('client_info', 1, 'string'), ('api_version_major', 2, 'uint32'), ('api_version_minor', 3, 'uint32')],
    'HelloResponse': [('api_version_major', 1, 'uint32'), ('api_version_minor', 2, 'uint32'),
                      ('server_info', 3, 'string'), ('name', 4, 'string')],
    'DeviceInfoResponse': [('uses_password', 1, 'bool'), ('name', 2, 'string'), ('mac_address', 3, 'string'),
                           ('esphome_version', 4, 'string'), ('compilation_time', 5, 'string'), ('model', 6, 'string'),
                           ('has_deep_sleep', 7, 'bool'), ('project_name', 8, 'string'),
                           ('project_version', 9, 'string'), ('webserver_port', 10, 'uint32'),
                           ('manufacturer', 12, 'string'), ('friendly_name', 13, 'string'),
                           ('suggested_area', 16, 'string'), ('api_encryption_supported', 19, 'bool')],
    'ListEntitiesBinarySensorResponse': [('object_id', 1, 'string'), ('key', 2, 'fixed32'), ('name', 3, 'string'),
                                         ('device_class', 5, 'string'), ('is_status_binary_sensor', 6, 'bool'),
                                         ('disabled_by_default', 7, 'bool'), ('icon', 8, 'string'),
                                         ('entity_category', 9, 'enum')],
    'ListEntitiesLightResponse': [('object_id', 1, 'string'), ('key', 2, 'fixed32'), ('name', 3, 'string'),
                                  ('supported_color_modes', 12, 'enum*'), ('disabled_by_default', 13, 'bool'),
                                  ('icon', 14, 'string'), ('entity_category', 15, 'enum')],
    'ListEntitiesSensorResponse': [('object_id', 1, 'string'), ('key', 2, 'fixed32'), ('name', 3, 'string'),
                                   ('icon', 5, 'string'), ('unit_of_measurement', 6, 'string'),
                                   ('accuracy_decimals', 7, 'int32'), ('force_update', 8, 'bool'),
                                   ('device_class', 9, 'string'), ('state_class', 10, 'enum'),
                                   ('disabled_by_default', 12, 'bool'), ('entity_category', 13, 'enum')],
    'ListEntitiesSelectResponse': [('object_id', 1, 'string'), ('key', 2, 'fixed32'), ('name', 3, 'string'),
                                   ('icon', 5, 'string'), ('options', 6, 'string*'),
                                   ('disabled_by_default', 7, 'bool'), ('entity_category', 8, 'enum')],
    'ListEntitiesButtonResponse': [('object_id', 1, 'string'), ('key', 2, 'fixed32'), ('name', 3, 'string'),
                                   ('icon', 5, 'string'), ('disabled_by_default', 6, 'bool'),
                                   ('entity_category', 7, 'enum'), ('device_class', 8, 'string')],
    'ListEntitiesEventResponse': [('object_id', 1, 'string'), ('key', 2, 'fixed32'), ('name', 3, 'string'),
                                  ('icon', 5, 'string'), ('disabled_by_default', 6, 'bool'),
                                  ('entity_category', 7, 'enum'), ('device_class', 8, 'string'),
                                  ('event_types', 9, 'string*')],
    'BinarySensorStateResponse': [('key', 1, 'fixed32'), ('state', 2, 'bool'), ('missing_state', 3, 'bool')],
    'LightStateResponse': [('key', 1, 'fixed32'), ('state', 2, 'bool'), ('brightness', 3, 'float'),
                           ('color_mode', 11, 'enum')],
    'SensorStateResponse': [('key', 1, 'fixed32'), ('state', 2, 'float'), ('missing_state', 3, 'bool')],
    'SelectStateResponse': [('key', 1, 'fixed32'), ('state', 2, 'string'), ('missing_state', 3, 'bool')],
    'EventResponse': [('key', 1, 'fixed32'), ('event_type', 2, 'string')],
    'LightCommandRequest': [('key', 1, 'fixed32'), ('has_state', 2, 'bool'), ('state', 3, 'bool'),
                            ('has_brightness', 4, 'bool'), ('brightness', 5, 'float')],
    'SelectCommandRequest': [('key', 1, 'fixed32'), ('state', 2, 'string')],
    'ButtonCommandRequest': [('key', 1, 'fixed32')],
    'DSTRule': [('time_seconds', 1, 'sint32'), ('day', 2, 'uint32'), ('type', 3, 'enum'), ('month', 4, 'uint32'),
                ('week', 5, 'uint32'), ('day_of_week', 6, 'uint32')],
    'ParsedTimezone': [('std_offset_seconds', 1, 'sint32'), ('dst_offset_seconds', 2, 'sint32'),
                       ('dst_start', 3, 'msg:DSTRule'), ('dst_end', 4, 'msg:DSTRule')],
    'GetTimeResponse': [('epoch_seconds', 1, 'fixed32'), ('timezone', 2, 'string'),
                        ('parsed_timezone', 3, 'msg:ParsedTimezone')],
}


def classes():
    try:
        from aioesphomeapi import api_pb2  # noqa: PLC0415
        return {name: getattr(api_pb2, name) for name in FIELDS}, 'aioesphomeapi api_pb2'
    except ImportError:
        pass
    from google.protobuf import descriptor_pb2, descriptor_pool, message_factory  # noqa: PLC0415
    F = descriptor_pb2.FieldDescriptorProto
    types = {'string': F.TYPE_STRING, 'uint32': F.TYPE_UINT32, 'int32': F.TYPE_INT32, 'bool': F.TYPE_BOOL,
             'fixed32': F.TYPE_FIXED32, 'float': F.TYPE_FLOAT, 'enum': F.TYPE_UINT32, 'sint32': F.TYPE_SINT32}
    file = descriptor_pb2.FileDescriptorProto(name='tessera_api_subset.proto', package='subset', syntax='proto3')
    for name, fields in FIELDS.items():
        message = file.message_type.add(name=name)
        for field, number, kind in fields:
            repeated = kind.endswith('*')
            base = kind.rstrip('*')
            label = F.LABEL_REPEATED if repeated else F.LABEL_OPTIONAL
            if base.startswith('msg:'):
                message.field.add(name=field, number=number, type=F.TYPE_MESSAGE, label=label,
                                  type_name='.subset.' + base[4:])
                continue
            # A repeated enum is packed in proto3; uint32 has the same packed varint encoding.
            message.field.add(name=field, number=number, type=types[base], label=label)
    pool = descriptor_pool.DescriptorPool()
    pool.Add(file)
    return ({name: message_factory.GetMessageClass(pool.FindMessageTypeByName('subset.' + name)) for name in FIELDS},
            'descriptors copied from api.proto')


def fixtures(c):
    def tz(std, dst, start, end):  # POSIX-style offsets (positive west), as esphome's time/posix_tz.h has them
        rule = c['DSTRule']
        return c['ParsedTimezone'](std_offset_seconds=std, dst_offset_seconds=dst,
                                   dst_start=rule(type=1, month=start[0], week=start[1], day_of_week=start[2],
                                                  time_seconds=start[3]),
                                   dst_end=rule(type=1, month=end[0], week=end[1], day_of_week=end[2],
                                                time_seconds=end[3]))
    return {
        'hello_response': c['HelloResponse'](api_version_major=1, api_version_minor=12, server_info='Tessera 0.8.0',
                                             name='tessera-deck'),
        'device_info': c['DeviceInfoResponse'](
            name='tessera-deck', mac_address='AA:BB:CC:DD:EE:FF', esphome_version='2026.11.0',
            compilation_time='Nov 14 2026, 12:00:00', model='Guition JC1060P470C',
            project_name='catorendal-a11y.tessera-deck', project_version='0.8.0', manufacturer='Tessera',
            friendly_name='Tessera Deck', suggested_area='Office', api_encryption_supported=True),
        'list_binary_sensor': c['ListEntitiesBinarySensorResponse'](
            object_id='pc_connected', key=fnv1('pc_connected'), name='PC connected', device_class='connectivity'),
        'list_light': c['ListEntitiesLightResponse'](
            object_id='backlight', key=fnv1('backlight'), name='Backlight', supported_color_modes=[3]),
        'list_sensor': c['ListEntitiesSensorResponse'](
            object_id='wifi_signal', key=fnv1('wifi_signal'), name='Wi-Fi signal', unit_of_measurement='dBm',
            device_class='signal_strength', state_class=1, entity_category=2),
        'list_select_profile': c['ListEntitiesSelectResponse'](
            object_id='profile', key=fnv1('profile'), name='Profile', options=['Main', 'Chrome']),
        'list_select_page': c['ListEntitiesSelectResponse'](object_id='page', key=fnv1('page'), name='Page',
                                                             options=['main']),
        'list_button': c['ListEntitiesButtonResponse'](
            object_id='show_clock', key=fnv1('show_clock'), name='Show clock', icon='mdi:clock-outline'),
        'list_event_1': c['ListEntitiesEventResponse'](
            object_id='key_1', key=fnv1('key_1'), name='Key 1', device_class='button',
            event_types=['press', 'hold', 'double']),
        'list_event_13': c['ListEntitiesEventResponse'](
            object_id='key_13', key=fnv1('key_13'), name='Key 13', device_class='button', disabled_by_default=True,
            event_types=['press', 'hold', 'double']),
        'state_binary_sensor': c['BinarySensorStateResponse'](key=fnv1('pc_connected'), state=True),
        'state_light': c['LightStateResponse'](key=fnv1('backlight'), state=True, brightness=0.5, color_mode=3),
        'state_sensor': c['SensorStateResponse'](key=fnv1('wifi_signal'), state=-58.0),
        'state_sensor_missing': c['SensorStateResponse'](key=fnv1('wifi_signal'), missing_state=True),
        'state_select': c['SelectStateResponse'](key=fnv1('profile'), state='Main'),
        'event_double': c['EventResponse'](key=fnv1('key_1'), event_type='double'),
        'hello_request': c['HelloRequest'](client_info='aioesphomeapi', api_version_major=1, api_version_minor=10),
        'light_command': c['LightCommandRequest'](key=fnv1('backlight'), has_state=True, state=True,
                                                  has_brightness=True, brightness=0.3),
        'light_off': c['LightCommandRequest'](key=fnv1('backlight'), has_state=True, state=False),
        'select_command': c['SelectCommandRequest'](key=fnv1('profile'), state='Chrome'),
        'button_command': c['ButtonCommandRequest'](key=fnv1('show_clock')),
        # What HA 2026.9+ sends: the deprecated string for older firmware, and the parsed zone.
        'get_time_response': c['GetTimeResponse'](epoch_seconds=1763121600, timezone='CET-1CEST,M3.5.0,M10.5.0/3',
                                                  parsed_timezone=tz(-3600, -7200, (3, 5, 0, 7200), (10, 5, 0, 10800))),
        'get_time_parsed': c['GetTimeResponse'](epoch_seconds=1763121600,
                                                parsed_timezone=tz(18000, 14400, (3, 2, 0, 7200), (11, 1, 0, 7200))),
        'get_time_string': c['GetTimeResponse'](epoch_seconds=1763121600, timezone='CET-1CEST,M3.5.0,M10.5.0/3'),
        'get_time_iana': c['GetTimeResponse'](epoch_seconds=1763121600, timezone='Europe/Oslo'),
    }


def main():
    c, source = classes()
    OUT.mkdir(parents=True, exist_ok=True)
    for name, message in fixtures(c).items():
        (OUT / f'{name}.hex').write_text(message.SerializeToString().hex() + '\n', encoding='ascii')
    (OUT / 'README.md').write_text(
        '# ESPHome API golden bytes\n\nMade by `tools/gen_api_fixtures.py` from ' + source +
        '. `tests/native/test_api.cpp` checks the firmware codec against them.\n', encoding='utf-8')
    print(f'{len(fixtures(c))} fixtures from {source}')


if __name__ == '__main__':
    main()
