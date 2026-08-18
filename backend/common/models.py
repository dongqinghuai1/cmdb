"""通用抽象模型与枚举（ER 第 1 章总则）。"""
from django.db import models


class TimeStampedModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class SoftDeleteQuerySet(models.QuerySet):
    def delete(self):
        return super().update(deleted_at=django_now())

    def hard_delete(self):
        return super().delete()

    def alive(self):
        return self.filter(deleted_at__isnull=True)


def django_now():
    from django.utils import timezone
    return timezone.now()


class SoftDeleteModel(TimeStampedModel):
    deleted_at = models.DateTimeField(null=True, blank=True, db_index=True)

    objects = SoftDeleteQuerySet.as_manager()
    all_objects = models.Manager()  # 含已删除，审计用

    class Meta:
        abstract = True

    def delete(self, using=None, keep_parents=False):
        self.deleted_at = django_now()
        self.save(update_fields=["deleted_at", "updated_at"])


class Choices(models.TextChoices):
    """统一枚举基类（具体枚举定义在各 app models.py）。"""
