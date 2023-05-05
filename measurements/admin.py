from django.conf import settings
# from django.contrib import admin
from django.contrib.gis import admin
from .models import Parameter, Sensor, Location, Serie, Measure, Network, SourceType, Station, ParameterMapping
# from leaflet.admin import LeafletGeoAdmin

load_google = False
try:
    settings.MAP_WIDGETS['GOOGLE_MAP_API_KEY'] 
    from mapwidgets.widgets import GooglePointFieldInlineWidget
    from django.contrib.gis.db.models import GeometryField
    formfield_overrides = {
        GeometryField: {"widget": GooglePointFieldInlineWidget}
    }


    class LocationAdmin(admin.ModelAdmin):
        formfield_overrides = formfield_overrides

except (KeyError, AttributeError) as e:
    formfield_overrides = {}

    try:
        from leaflet.admin import LeafletGeoAdmin

        class LocationAdmin(LeafletGeoAdmin):
            display_raw = True

    except:
        class LocationAdmin(admin.ModelAdmin):
            display_raw = True


class ParameterAdmin(admin.ModelAdmin):
    pass


class SensorAdmin(admin.ModelAdmin):
    pass


class NetworkAdmin(admin.ModelAdmin):
    pass


class SerieAdmin(admin.ModelAdmin):
    list_display = ('station', 'location', 'sensor', 'parameter', 'height')
    list_filter = ('station', 'sensor', 'parameter')


class ParameterMappingInline(admin.TabularInline):
    model = ParameterMapping


class StationAdmin(admin.ModelAdmin):
    inlines = [ParameterMappingInline]
    pass


class SourceTypeAdmin(admin.ModelAdmin):
    pass


class MeasureAdmin(admin.ModelAdmin):
    list_display = ('serie', 'timestamp', 'value')


admin.site.register(Parameter, ParameterAdmin)
admin.site.register(Sensor, SensorAdmin)
admin.site.register(Location, LocationAdmin)
admin.site.register(Network, NetworkAdmin)
admin.site.register(Serie, SerieAdmin)
admin.site.register(Station, StationAdmin)
admin.site.register(SourceType, SourceTypeAdmin)
admin.site.register(Measure, MeasureAdmin)
