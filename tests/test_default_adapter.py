import threading
import pytest

from django.contrib import auth
from django.db import connection

from mellon.adapters import DefaultAdapter

pytestmark = pytest.mark.django_db

idp = {}
saml_attributes = {
    'name_id_content': 'x' * 32,
    'issuer': 'https://idp.example.net/saml/metadata',
    'username': ['foobar'],
    'email': ['test@example.net'],
    'first_name': ['Foo'],
    'last_name': ['Bar'],
    'is_superuser': ['true'],
    'group': ['GroupA', 'GroupB', 'GroupC'],
}


def test_format_username(settings):
    adapter = DefaultAdapter()
    assert adapter.format_username(idp, {}) is None
    assert adapter.format_username(idp, saml_attributes) == ('x' * 32 + '@saml')[:30]
    settings.MELLON_USERNAME_TEMPLATE = '{attributes[name_id_content]}'
    assert adapter.format_username(idp, saml_attributes) == ('x' * 32)[:30]
    settings.MELLON_USERNAME_TEMPLATE = '{attributes[username][0]}'
    assert adapter.format_username(idp, saml_attributes) == 'foobar'


def test_lookup_user(settings):
    User = auth.get_user_model()
    adapter = DefaultAdapter()
    user = adapter.lookup_user(idp, saml_attributes)
    assert user is not None

    user2 = adapter.lookup_user(idp, saml_attributes)
    assert user.id == user2.id

    User.objects.all().delete()
    assert User.objects.count() == 0

    settings.MELLON_PROVISION = False
    user = adapter.lookup_user(idp, saml_attributes)
    assert user is None
    assert User.objects.count() == 0


def test_lookup_user_transaction(transactional_db, concurrency):
    adapter = DefaultAdapter()
    N = 30
    def map_threads(f, l):
        threads = []
        for i in l:
            threads.append(threading.Thread(target=f, args=(i,)))
            threads[-1].start()
        for thread in threads:
            thread.join()
    users = []

    def f(i):
        users.append(adapter.lookup_user(idp, saml_attributes))
        connection.close()
    map_threads(f, range(concurrency))
    assert len(users) == concurrency
    assert len(set(user.pk for user in users)) == 1


def test_provision(settings):
    settings.MELLON_GROUP_ATTRIBUTE = 'group'
    User = auth.get_user_model()
    adapter = DefaultAdapter()
    settings.MELLON_ATTRIBUTE_MAPPING = {
        'email': '{attributes[email][0]}',
        'first_name': '{attributes[first_name][0]}',
        'last_name': '{attributes[last_name][0]}',
    }
    user = User(username='xx')
    user.save()
    adapter.provision(user, idp, saml_attributes)
    assert user.first_name == 'Foo'
    assert user.last_name == 'Bar'
    assert user.email == 'test@example.net'
    assert user.is_superuser is False
    assert user.groups.count() == 3
    assert set(user.groups.values_list('name', flat=True)) == set(saml_attributes['group'])
    saml_attributes2 = saml_attributes.copy()
    saml_attributes2['group'] = ['GroupB', 'GroupC']
    adapter.provision(user, idp, saml_attributes2)
    assert user.groups.count() == 2
    assert set(user.groups.values_list('name', flat=True)) == set(saml_attributes2['group'])
    User.objects.all().delete()

    settings.MELLON_SUPERUSER_MAPPING = {
        'is_superuser': 'true',
    }
    user = User(username='xx')
    user.save()
    adapter.provision(user, idp, saml_attributes)
    assert user.is_superuser is True
    User.objects.all().delete()

    local_saml_attributes = saml_attributes.copy()
    del local_saml_attributes['email']
    user = User(username='xx')
    user.save()
    adapter.provision(user, idp, local_saml_attributes)
    assert not user.email
    User.objects.all().delete()

    local_saml_attributes = saml_attributes.copy()
    settings.MELLON_ATTRIBUTE_MAPPING = {
        'email': '{attributes[email][0]}',
        'first_name': '{attributes[first_name][0]}',
        'last_name': '{attributes[last_name][0]}',
    }
    local_saml_attributes['first_name'] = [('y' * 32)]
    user = User(username='xx')
    user.save()
    adapter.provision(user, idp, local_saml_attributes)
    assert user.first_name == 'y' * 30
    User.objects.all().delete()
