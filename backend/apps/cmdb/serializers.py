from rest_framework import serializers

from apps.cmdb.models import (Business, CiModel, CiModelAttr, Device,
                              DeviceGroup, DeviceInterface)
from apps.cmdb.services import DeviceService


class CiModelAttrSerializer(serializers.ModelSerializer):
    class Meta:
        model = CiModelAttr
        fields = "__all__"

    def validate_code(self, v):
        if v in DeviceService.BUILTIN:
            raise serializers.ValidationError(f"conflicts with builtin field: {v}")
        return v


class CiModelSerializer(serializers.ModelSerializer):
    attrs_def = CiModelAttrSerializer(many=True, read_only=True)

    class Meta:
        model = CiModel
        fields = "__all__"


class DeviceSerializer(serializers.ModelSerializer):
    model_code = serializers.CharField(source="model.code", read_only=True)
    model_name = serializers.CharField(source="model.name", read_only=True)
    site_name = serializers.CharField(source="site.name", read_only=True, default="")
    region_name = serializers.CharField(source="region.name", read_only=True, default="")
    rack_name = serializers.CharField(source="rack.name", read_only=True, default="")
    owner_name = serializers.CharField(source="owner.username", read_only=True, default="")

    class Meta:
        model = Device
        fields = "__all__"
        read_only_fields = ["online_status", "last_seen_at", "usage_status"]

    def validate(self, attrs):
        ci = attrs.get("model") or getattr(self.instance, "model", None)
        if ci:
            try:
                DeviceService.validate_attrs(ci, attrs.get("attrs", {}) or
                                             (self.instance.attrs if self.instance else {}))
            except ValueError as e:
                raise serializers.ValidationError(str(e))
        # PATCH 时未传的字段取实例当前值（部分更新语义）
        inst = self.instance
        rack = attrs.get("rack", getattr(inst, "rack", None) if inst else None)
        start_u = attrs.get("rack_start_u", getattr(inst, "rack_start_u", None) if inst else None)
        if rack and not start_u:
            raise serializers.ValidationError("rack_start_u is required when rack is set")
        return attrs


class DeviceGroupSerializer(serializers.ModelSerializer):
    member_count = serializers.SerializerMethodField()

    class Meta:
        model = DeviceGroup
        fields = "__all__"

    def get_member_count(self, obj):
        return len(obj.member_ids())


class DeviceInterfaceSerializer(serializers.ModelSerializer):
    class Meta:
        model = DeviceInterface
        fields = "__all__"


class BusinessSerializer(serializers.ModelSerializer):
    class Meta:
        model = Business
        fields = "__all__"

