# TODO: cleanup imports
from django.contrib import admin
from django import forms, template
from django.forms.formsets import all_valid
from django.forms.models import (modelform_factory, modelformset_factory,
    inlineformset_factory, BaseInlineFormSet)
from django.contrib.contenttypes.models import ContentType
from django.contrib.admin import widgets, helpers
from django.contrib.admin.util import unquote, flatten_fieldsets, get_deleted_objects, model_format_dict
from django.contrib import messages
from django.views.decorators.csrf import csrf_protect
from django.core.exceptions import PermissionDenied, ValidationError,\
    ImproperlyConfigured
from django.core.paginator import Paginator
from django.db import models, transaction, router
from django.db.models.related import RelatedObject
from django.db.models.fields import BLANK_CHOICE_DASH, FieldDoesNotExist
from django.db.models.sql.constants import LOOKUP_SEP, QUERY_TERMS
from django.http import Http404, HttpResponse, HttpResponseRedirect
from django.shortcuts import get_object_or_404, render_to_response
from django.utils.decorators import method_decorator
from django.utils.datastructures import SortedDict
from django.utils.functional import update_wrapper
from django.utils.html import escape, escapejs
from django.utils.safestring import mark_safe
from django.utils.functional import curry
from django.utils.text import capfirst, get_text_list
from django.utils.translation import ugettext as _
from django.utils.translation import ungettext
from django.utils.encoding import force_unicode
csrf_protect_m = method_decorator(csrf_protect)


from polymorphic.base import PolymorphicModelBase

# TODOS:
# - saving of inlines
# - creation form

class PolymorphicAdmin(admin.ModelAdmin):
    """
    ModelAdmin to enable the listing of all models inheriting from the 
    polymorphic base class within one AdminSite.
    """
    
    def get_model_inline_instances(self, object):
        """
        Returns the inline model instances for the given object.
        @param object: the currently being edited model
        """
        try:
            instances = []
            admin_site = admin.site._registry.get(type(object))
            for inline_class in admin_site.inlines:
                instances.append(inline_class(type(object), admin.site))
            return instances
        except:
            raise ImproperlyConfigured(
                'AdminSite for model %s is not registered' % type(object)
            )
        
    def get_model_formsets(self, request, obj):
        for inline in self.get_model_inline_instances(obj):
            yield inline.get_formset(request, obj)

    def get_readonly_fields(self, request, obj=None):
        """
        Returns the readonly fields for the object.
        @return tuple
        """
        if obj is not None:
            try:
                # get the AdminSite for the current object
                admin_site = admin.site._registry.get(type(obj))
            except:
                raise ImproperlyConfigured(
                    'AdminSite for model %s is not registered' % type(obj)
                )
            else:
                return admin_site.readonly_fields
        else:
            # fallback
            return self.readonly_fields
            
    @csrf_protect_m
    @transaction.commit_on_success
    def change_view(self, request, object_id, extra_context=None):
        "The 'change' admin view for this model."
        model = self.model
        opts = model._meta

        obj = self.get_object(request, unquote(object_id))
        ### START: NEW CODE ###
        if isinstance(model, PolymorphicModelBase):
            model = type(obj)
            opts = model._meta
        ### END: NEW CODE ###
        
        if not self.has_change_permission(request, obj):
            raise PermissionDenied

        if obj is None:
            raise Http404(_('%(name)s object with primary key %(key)r does not exist.') % {'name': force_unicode(opts.verbose_name), 'key': escape(object_id)})

        if request.method == 'POST' and "_saveasnew" in request.POST:
            return self.add_view(request, form_url='../add/')

        ModelForm = self.get_form(request, obj)
        formsets = []
        if request.method == 'POST':
            form = ModelForm(request.POST, request.FILES, instance=obj)
            if form.is_valid():
                form_validated = True
                new_object = self.save_form(request, form, change=True)
            else:
                form_validated = False
                new_object = obj
            prefixes = {}
            ## START_ ADJUSTED CODE ###
            for FormSet, inline in zip(self.get_model_formsets(request, obj), self.get_model_inline_instances(obj)):
            ### END: ADJUSTED CODE ###
                prefix = FormSet.get_default_prefix()
                prefixes[prefix] = prefixes.get(prefix, 0) + 1
                if prefixes[prefix] != 1:
                    prefix = "%s-%s" % (prefix, prefixes[prefix])
                formset = FormSet(request.POST, request.FILES,
                                  instance=new_object, prefix=prefix,
                                  queryset=inline.queryset(request))

                formsets.append(formset)
            if all_valid(formsets) and form_validated:
                self.save_model(request, new_object, form, change=True)
                form.save_m2m()
                for formset in formsets:
                    self.save_formset(request, form, formset, change=True)

                change_message = self.construct_change_message(request, form, formsets)
                self.log_change(request, new_object, change_message)
                return self.response_change(request, new_object)

        else:
            form = ModelForm(instance=obj)
            prefixes = {}
            ## START_ ADJUSTED CODE ###
            for FormSet, inline in zip(self.get_model_formsets(request, obj), self.get_model_inline_instances(obj)):
            ### END: ADJUSTED CODE ###
                prefix = FormSet.get_default_prefix()
                prefixes[prefix] = prefixes.get(prefix, 0) + 1
                if prefixes[prefix] != 1:
                    prefix = "%s-%s" % (prefix, prefixes[prefix])
                formset = FormSet(instance=obj, prefix=prefix,
                                  queryset=inline.queryset(request))
                formsets.append(formset)

        print self.get_readonly_fields(request, obj)
        adminForm = helpers.AdminForm(form, self.get_fieldsets(request, obj),
            self.prepopulated_fields, self.get_readonly_fields(request, obj),
            model_admin=self)
        media = self.media + adminForm.media

        inline_admin_formsets = []
        ### START: ADJUSTED CODE ###
        for inline, formset in zip(self.get_model_inline_instances(obj), formsets):
        ### END: ADJUSTED CODE ###
            fieldsets = list(inline.get_fieldsets(request, obj))
            readonly = list(inline.get_readonly_fields(request, obj))
            inline_admin_formset = helpers.InlineAdminFormSet(inline, formset,
                fieldsets, readonly, model_admin=self)
            inline_admin_formsets.append(inline_admin_formset)
            media = media + inline_admin_formset.media

        context = {
            'title': _('Change %s') % force_unicode(opts.verbose_name),
            'adminform': adminForm,
            'object_id': object_id,
            'original': obj,
            'is_popup': "_popup" in request.REQUEST,
            'media': mark_safe(media),
            'inline_admin_formsets': inline_admin_formsets,
            'errors': helpers.AdminErrorList(form, formsets),
            'root_path': self.admin_site.root_path,
            'app_label': opts.app_label,
        }
        context.update(extra_context or {})
        return self.render_change_form(request, context, change=True, obj=obj)
    
    def get_form(self, request, obj=None, **kwargs):
        """
        Returns a Form class for use in the admin add view. This is used by
        add_view and change_view.
        """
        if self.declared_fieldsets:
            fields = flatten_fieldsets(self.declared_fieldsets)
        else:
            fields = None
        if self.exclude is None:
            exclude = []
        else:
            exclude = list(self.exclude)
        exclude.extend(kwargs.get("exclude", []))
        exclude.extend(self.get_readonly_fields(request, obj))
        # if exclude is an empty list we pass None to be consistant with the
        # default on modelform_factory
        exclude = exclude or None
        defaults = {
            "form": self.form,
            "fields": fields,
            "exclude": exclude,
            "formfield_callback": curry(self.formfield_for_dbfield, request=request),
        }
        defaults.update(kwargs)
        ### START: ADJUSTED CODE ###
        return modelform_factory(type(obj), **defaults)
        ### END: ADJUSTED CODE ###