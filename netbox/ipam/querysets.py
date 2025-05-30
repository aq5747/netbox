from django.contrib.contenttypes.models import ContentType
from django.db.models import Count, F, OuterRef, Q, Subquery, Value
from django.db.models.expressions import RawSQL
from django.db.models.functions import Round

from utilities.query import count_related
from utilities.querysets import RestrictedQuerySet

__all__ = (
    'ASNRangeQuerySet',
    'PrefixQuerySet',
    'VLANGroupQuerySet',
    'VLANQuerySet',
)


class ASNRangeQuerySet(RestrictedQuerySet):

    def annotate_asn_counts(self):
        """
        Annotate the number of ASNs which appear within each range.
        """
        from .models import ASN

        # Because ASN does not have a foreign key to ASNRange, we create a fake column "_" with a consistent value
        # that we can use to count ASNs and return a single value per ASNRange.
        asns = ASN.objects.filter(
            asn__gte=OuterRef('start'),
            asn__lte=OuterRef('end')
        ).order_by().annotate(_=Value(1)).values('_').annotate(c=Count('*')).values('c')

        return self.annotate(asn_count=Subquery(asns))


class PrefixQuerySet(RestrictedQuerySet):

    def annotate_hierarchy(self):
        """
        Annotate the depth and number of child prefixes for each Prefix. Cast null VRF values to zero for
        comparison. (NULL != NULL).
        """
        return self.annotate(
            hierarchy_depth=RawSQL(
                'SELECT COUNT(DISTINCT U0."prefix") AS "c" '
                'FROM "ipam_prefix" U0 '
                'WHERE (U0."prefix" >> "ipam_prefix"."prefix" '
                'AND COALESCE(U0."vrf_id", 0) = COALESCE("ipam_prefix"."vrf_id", 0))',
                ()
            ),
            hierarchy_children=RawSQL(
                'SELECT COUNT(U1."prefix") AS "c" '
                'FROM "ipam_prefix" U1 '
                'WHERE (U1."prefix" << "ipam_prefix"."prefix" '
                'AND COALESCE(U1."vrf_id", 0) = COALESCE("ipam_prefix"."vrf_id", 0))',
                ()
            )
        )


class VLANGroupQuerySet(RestrictedQuerySet):

    def annotate_utilization(self):
        from .models import VLAN

        return self.annotate(
            vlan_count=count_related(VLAN, 'group'),
            utilization=Round(F('vlan_count') * 100.0 / F('_total_vlan_ids'), 2)
        )


class VLANQuerySet(RestrictedQuerySet):

    def get_for_site(self, site):
        """
        Return all VLANs in the specified site
        """
        from .models import VLANGroup
        q = Q()
        q |= Q(
            scope_type=ContentType.objects.get_by_natural_key('dcim', 'site'),
            scope_id=site.pk
        )

        if site.region:
            q |= Q(
                scope_type=ContentType.objects.get_by_natural_key('dcim', 'region'),
                scope_id__in=site.region.get_ancestors(include_self=True)
            )
        if site.group:
            q |= Q(
                scope_type=ContentType.objects.get_by_natural_key('dcim', 'sitegroup'),
                scope_id__in=site.group.get_ancestors(include_self=True)
            )

        return self.filter(
            Q(group__in=VLANGroup.objects.filter(q)) |
            Q(site=site) |
            Q(group__scope_id__isnull=True, site__isnull=True) |  # Global group VLANs
            Q(group__isnull=True, site__isnull=True)  # Global VLANs
        )

    def get_for_device(self, device):
        """
        Return all VLANs available to the specified Device.
        """
        from .models import VLANGroup

        # Find all relevant VLANGroups
        q = Q()
        if device.site.region:
            q |= Q(
                scope_type=ContentType.objects.get_by_natural_key('dcim', 'region'),
                scope_id__in=device.site.region.get_ancestors(include_self=True)
            )
        if device.site.group:
            q |= Q(
                scope_type=ContentType.objects.get_by_natural_key('dcim', 'sitegroup'),
                scope_id__in=device.site.group.get_ancestors(include_self=True)
            )
        q |= Q(
            scope_type=ContentType.objects.get_by_natural_key('dcim', 'site'),
            scope_id=device.site_id
        )
        if device.location:
            q |= Q(
                scope_type=ContentType.objects.get_by_natural_key('dcim', 'location'),
                scope_id__in=device.location.get_ancestors(include_self=True)
            )
        if device.rack:
            q |= Q(
                scope_type=ContentType.objects.get_by_natural_key('dcim', 'rack'),
                scope_id=device.rack_id
            )

        # Return all applicable VLANs
        return self.filter(
            Q(group__in=VLANGroup.objects.filter(q)) |
            Q(site=device.site) |
            Q(group__scope_id__isnull=True, site__isnull=True) |  # Global group VLANs
            Q(group__isnull=True, site__isnull=True)  # Global VLANs
        )

    def get_for_virtualmachine(self, vm):
        """
        Return all VLANs available to the specified VirtualMachine.
        """
        from .models import VLANGroup

        # Find all relevant VLANGroups
        q = Q()
        site = vm.site
        if vm.cluster:
            # Add VLANGroups scoped to the assigned cluster (or its group)
            q |= Q(
                scope_type=ContentType.objects.get_by_natural_key('virtualization', 'cluster'),
                scope_id=vm.cluster_id
            )
            if vm.cluster.group:
                q |= Q(
                    scope_type=ContentType.objects.get_by_natural_key('virtualization', 'clustergroup'),
                    scope_id=vm.cluster.group_id
                )
            # Looking all possible cluster scopes
            if vm.cluster.scope_type == ContentType.objects.get_by_natural_key('dcim', 'location'):
                site = site or vm.cluster.scope.site
                q |= Q(
                    scope_type=ContentType.objects.get_by_natural_key('dcim', 'location'),
                    scope_id__in=vm.cluster.scope.get_ancestors(include_self=True)
                )
            elif vm.cluster.scope_type == ContentType.objects.get_by_natural_key('dcim', 'site'):
                site = site or vm.cluster.scope
                q |= Q(
                    scope_type=ContentType.objects.get_by_natural_key('dcim', 'site'),
                    scope_id=vm.cluster.scope.pk
                )
            elif vm.cluster.scope_type == ContentType.objects.get_by_natural_key('dcim', 'sitegroup'):
                q |= Q(
                    scope_type=ContentType.objects.get_by_natural_key('dcim', 'sitegroup'),
                    scope_id__in=vm.cluster.scope.get_ancestors(include_self=True)
                )
            elif vm.cluster.scope_type == ContentType.objects.get_by_natural_key('dcim', 'region'):
                q |= Q(
                    scope_type=ContentType.objects.get_by_natural_key('dcim', 'region'),
                    scope_id__in=vm.cluster.scope.get_ancestors(include_self=True)
                )
        # VM can be assigned to a site without a cluster so checking assigned site independently
        if site:
            # Add VLANGroups scoped to the assigned site (or its group or region)
            q |= Q(
                scope_type=ContentType.objects.get_by_natural_key('dcim', 'site'),
                scope_id=site.pk
            )
            if site.region:
                q |= Q(
                    scope_type=ContentType.objects.get_by_natural_key('dcim', 'region'),
                    scope_id__in=site.region.get_ancestors(include_self=True)
                )
            if site.group:
                q |= Q(
                    scope_type=ContentType.objects.get_by_natural_key('dcim', 'sitegroup'),
                    scope_id__in=site.group.get_ancestors(include_self=True)
                )
        vlan_groups = VLANGroup.objects.filter(q)

        # Return all applicable VLANs
        q = (
            Q(group__in=vlan_groups) |
            Q(group__scope_id__isnull=True, site__isnull=True) |  # Global group VLANs
            Q(group__isnull=True, site__isnull=True)  # Global VLANs
        )
        if site:
            q |= Q(site=site)

        return self.filter(q)
