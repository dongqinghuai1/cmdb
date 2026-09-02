from rest_framework import serializers

from apps.dcim.models import (Cable, DcimTicket, PowerSample, Rack,
                              RackReservation, Region, Site, SiteObject)


class PowerSampleSerializer(serializers.ModelSerializer):
    source_label = serializers.CharField(source="get_source_display", read_only=True)

    class Meta:
        model = PowerSample
        fields = ["id", "device_id", "outlet", "watts", "current_a", "voltage_v",
                  "utilization_pct", "rated_watts", "source", "source_label",
                  "sampled_at", "created_at"]


class RegionSerializer(serializers.ModelSerializer):
    site_count = serializers.IntegerField(read_only=True, default=0)

    class Meta:
        model = Region
        fields = ["id", "parent", "name", "code", "manager_id", "remark", "site_count"]


class SiteSerializer(serializers.ModelSerializer):
    region_name = serializers.CharField(source="region.name", read_only=True)
    rack_count = serializers.IntegerField(read_only=True, default=0)

    class Meta:
        model = Site
        fields = "__all__"


class RackSerializer(serializers.ModelSerializer):
    site_name = serializers.CharField(source="site.name", read_only=True)
    used_u = serializers.IntegerField(read_only=True, default=0)

    class Meta:
        model = Rack
        fields = "__all__"


class RackReservationSerializer(serializers.ModelSerializer):
    class Meta:
        model = RackReservation
        fields = "__all__"

    def validate(self, attrs):
        from apps.dcim.services import RackService
        RackService.check_placement(attrs["rack"].id, attrs["start_u"], attrs.get("units", 1))
        return attrs


class CableSerializer(serializers.ModelSerializer):
    class Meta:
        model = Cable
        fields = "__all__"


class SiteObjectSerializer(serializers.ModelSerializer):
    class Meta:
        model = SiteObject
        fields = "__all__"


class DcimTicketSerializer(serializers.ModelSerializer):
    rack_name = serializers.CharField(source="rack.name", read_only=True, default="")
    kind_label = serializers.CharField(source="get_kind_display", read_only=True)
    status_label = serializers.CharField(source="get_status_display", read_only=True)

    class Meta:
        model = DcimTicket
        fields = "__all__"
