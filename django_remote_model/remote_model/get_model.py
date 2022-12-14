from dataclasses import field
from django.db import models
import requests
from types import new_class, FunctionType, MethodType

from django.apps import apps

import inspect
from .queryset import RemoteModelQuerySet
from django.contrib.auth.models import Permission
from django.contrib.contenttypes.models import ContentType


class RemoteModel(RemoteModelQuerySet):

    def __init__(self, model_name, provider_dict_api_url, model_base_url, api_key_header_name, api_key, app_name=None, has_permission=False):
        self.model_name = model_name
        self.provider_dict_api_url = provider_dict_api_url
        self.model_base_url = model_base_url
        self.api_key_header_name = api_key_header_name
        self.api_key = api_key
        self.app_name = app_name or self.__get_app_name()
        self.has_permission = has_permission

    def make_query_request(self, method_type, url, api_key_header_name, api_key, payload=None, params=None):
        method = getattr(requests, method_type)

        response = method(url, json=payload, params=params, headers={api_key_header_name: api_key})
        try:
            return response.json(), response.status_code
        except Exception as e:
            return response.text, response.status_code

    def get_model_manager(dynamic_instance, model, ):

        class model_manager(models.Manager):

            def get_queryset(self):
                return dynamic_instance.queryset_factory(model, dynamic_instance.provider_dict_api_url, dynamic_instance.model_base_url, dynamic_instance.api_key_header_name, dynamic_instance.api_key)

        return model_manager()

    @staticmethod
    def get_field(**kwargs):
        type = getattr(models, kwargs.pop('type'))
        return type(**kwargs)

    def get_model_fields(self):
        response = requests.get(self.provider_dict_api_url, headers={self.api_key_header_name: self.api_key})
        model_data = response.json()
        model_fields = {
            field['name']: RemoteModel.get_field(**field) for field in model_data
        }
        model_fields['__module__'] = f'{self.app_name}.models.{self.model_name}'

        return model_fields

    def __get_app_name(self):
        stack_trace = inspect.stack()
        file_path = stack_trace[1].filename
        module = inspect.getmodule(inspect.stack()[2][0])
        return apps.get_containing_app_config(module.__name__).name

    def generate_model(dyanmic_instance):

        def save(self, *args, **kwargs):
            id = getattr(self, 'id', None)
            model_data = {field.name: getattr(self, field.name) for field in self._meta.fields if field.name not in ['id', '_state']}
            if id is None:
                self.make_query_request('post', f"{dyanmic_instance.model_base_url}",
                                        dyanmic_instance.api_key_header_name, dyanmic_instance.api_key, payload=model_data)
            else:
                self.make_query_request('put', f"{dyanmic_instance.model_base_url}{id}/",
                                        dyanmic_instance.api_key_header_name, dyanmic_instance.api_key, payload=model_data)

        def delete(self, *args, **kwargs):
            id = getattr(self, 'id', None)
            if id is not None:
                self.make_query_request('delete', f"{dyanmic_instance.model_base_url}{id}/",
                                        dyanmic_instance.api_key_header_name, dyanmic_instance.api_key)

        attrs = dyanmic_instance.get_model_fields()
        model_for_manger = type(dyanmic_instance.model_name, (models.Model,), attrs)
        model_for_manger.save = save
        model_for_manger.delete = delete
        manger = dyanmic_instance.get_model_manager(model_for_manger)

        attrs1 = dyanmic_instance.get_model_fields()
        attrs1['objects'] = manger
        model = type(dyanmic_instance.model_name, (models.Model,), attrs1)
        model.save = save
        model.delete = delete
        dyanmic_instance.model = model
        dyanmic_instance.generate_permissions()
        return dyanmic_instance

    def __getattr__(self, name):
        if name == 'model':
            self.generate_model()
            return self.model
        else:
            raise AttributeError(f'{name} is not defined')

    def update(self):
        self.model = self.generate_model().model

    def generate_permissions(self):
        if self.has_permission:
            content_type = ContentType.objects.get_for_model(self.model)
            Permission.objects.get_or_create(codename='add_'+self.model_name.lower(), name='Can add '+self.model_name, content_type=content_type)
            Permission.objects.get_or_create(codename='change_'+self.model_name.lower(),
                                             name='Can change '+self.model_name, content_type=content_type)
            Permission.objects.get_or_create(codename='delete_'+self.model_name.lower(),
                                             name='Can delete '+self.model_name, content_type=content_type)
            Permission.objects.get_or_create(codename='view_'+self.model_name.lower(), name='Can view '+self.model_name, content_type=content_type)
