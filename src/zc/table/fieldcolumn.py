import re
from xml.sax.saxutils import quoteattr

from zope import interface, component, i18n
import zope.schema.interfaces
import zope.formlib.interfaces
import zope.formlib.form

from zope.app.form.interfaces import IInputWidget, IDisplayWidget
from zope.app.form.interfaces import WidgetInputError, WidgetsError

from zc.table import column

isSafe = re.compile(r'[\w +/]*$').match
def toSafe(string):
    # We don't want to use base64 unless we have to,
    # because it makes testing and reading html more difficult.  We make this
    # safe because all base64 strings will have a trailing '=', and our
    # `isSafe` regex does not allow '=' at all.  The only downside to the
    # approach is that a 'safe' string generated by the `toSafe` base64 code
    # will not pass the `isSafe` test, so the function is not idempotent.  The
    # simpler version (without the `isSafe` check) was not idempotent either,
    # so no great loss.
    if not isSafe(string):
        string = ''.join(string.encode('base64').split())
    return string

class BaseColumn(column.Column):

    ###### subclass helper API (not expected to be overridden) ######

    def getPrefix(self, item, formatter):
        prefix = self.getId(item, formatter)
        if formatter.prefix:
            prefix = '%s.%s' % (formatter.prefix, prefix)
        return prefix

    @property
    def key(self):
        return '%s.%s.%s' % (
            self.__class__.__module__,
            self.__class__.__name__,
            self.name)

    def setAnnotation(self, name, value, formatter):
        formatter.annotations[self.key + name] = value

    def getAnnotation(self, name, formatter, default=None):
        return formatter.annotations.get(self.key + name, default)

    ###### subclass customization API ######

    def getId(self, item, formatter):
        return toSafe(str(item))

class FieldColumn(BaseColumn):
    """Column that supports field/widget update

    Note that fields are only bound if bind == True.
    """

    __slots__ = ('title', 'name', 'field') # to emphasize that this should not
    # have thread-local attributes such as request

    def __init__(self, field, title=None, name=''):
        if zope.schema.interfaces.IField.providedBy(field):
            field = zope.formlib.form.FormField(field)
        else:
            assert zope.formlib.interfaces.IFormField.providedBy(field)
        self.field = field
        if title is None:
            title = self.field.field.title
        if not name and self.field.__name__:
            name = self.field.__name__
        super(FieldColumn, self).__init__(title, name)

    ###### subclass helper API (not expected to be overridden) ######

    def getInputWidget(self, item, formatter):
        form_field = self.field
        field = form_field.field
        request = formatter.request
        prefix = self.getPrefix(item, formatter)
        context = self.getFieldContext(item, formatter)
        if context is not None:
            field = form_field.field.bind(context)
        if form_field.custom_widget is None:
            if field.readonly or form_field.for_display:
                iface = IDisplayWidget
            else:
                iface = IInputWidget
            widget = component.getMultiAdapter((field, request), iface)
        else:
            widget = form_field.custom_widget(field, request)
        if form_field.prefix: # this should not be necessary AFAICT
            prefix = '%s.%s' % (prefix, form_field.prefix)
        widget.setPrefix(prefix)
        return widget

    def getRenderWidget(self, item, formatter, ignore_request=False):
        widget = self.getInputWidget(item, formatter)
        if (ignore_request or
            IDisplayWidget.providedBy(widget) or
            not widget.hasInput()):
            widget.setRenderedValue(self.get(item, formatter))
        return widget

    ###### subclass customization API ######

    def get(self, item, formatter):
        return self.field.field.get(item)

    def set(self, item, value, formatter):
        self.field.field.set(item, value)

    def getFieldContext(self, item, formatter):
        return None

    ###### main API: input, update, and custom renderCell ######

    def input(self, items, formatter):
        data = {}
        errors = []
        for item in items:
            widget = self.getInputWidget(item, formatter)
            if widget.hasInput():
                try:
                    data[self.getId(item, formatter)] = widget.getInputValue()
                except WidgetInputError, v:
                    errors.append(v)
        if errors:
            raise WidgetsError(errors)
        return data

    def update(self, items, data, formatter):
        changed = False
        for item in items:
            id = self.getId(item, formatter)
            v = data.get(id, self)
            if v is not self and self.get(item, formatter) != v:
                self.set(item, v, formatter)
                changed = True
        if changed:
            self.setAnnotation('changed', changed, formatter)
        return changed

    def renderCell(self, item, formatter):
        ignore_request = self.getAnnotation('changed', formatter)
        return self.getRenderWidget(
            item, formatter, ignore_request)()

class SubmitColumn(BaseColumn):

    ###### subclass helper API (not expected to be overridden) ######

    def getIdentifier(self, item, formatter):
        return '%s.%s' % (self.getPrefix(item, formatter), self.name)

    def renderWidget(self, item, formatter, **kwargs):
        res = ['%s=%s' % (k, quoteattr(v)) for k, v in kwargs.items()]
        lbl = self.getLabel(item, formatter)
        res[0:0] = [
            'input',
            'type="submit"',
            'name=%s' % quoteattr(self.getIdentifier(item, formatter)),
            'value=%s' % quoteattr(lbl)]
        return '<%s />' % (' '.join(res))

    ###### customization API (expected to be overridden) ######

    def getLabel(self, item, formatter):
        return super(SubmitColumn, self).renderHeader(formatter) # title

    ###### basic API ######

    def input(self, items, formatter):
        for item in items:
            if self.getIdentifier(item, formatter) in formatter.request.form:
                return item

    def update(self, items, item, formatter):
        raise NotImplementedError

    def renderCell(self, item, formatter):
        return self.renderWidget(item, formatter)

    def renderHeader(self, formatter):
        return ''