from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db.models import Count
from django.shortcuts import render
from django.views.decorators.http import require_safe

from .models import AnalysisJob, PersonPrediction

ACTIONS = (
    "bend_return", "drink_return", "leg_raise_lower",
    "sit_stand", "walk_turn_walk", "wave",
)


def chart_rows(counts, labels):
    return [(name, counts.get(name, 0)) for name in labels]


@login_required
@require_safe
def dashboard(request):
    if not request.user.is_active or not request.user.is_staff:
        raise PermissionDenied

    action_counts = dict(PersonPrediction.objects.filter(
        job__status=AnalysisJob.State.SUCCESS
    ).order_by().values("action_label").annotate(total=Count("pk")).values_list("action_label", "total"))
    state_counts = dict(AnalysisJob.objects.order_by().values("status").annotate(
        total=Count("pk")
    ).values_list("status", "total"))

    actions = chart_rows(action_counts, (*ACTIONS, "UNKNOWN"))
    states = chart_rows(state_counts, AnalysisJob.State.values)
    return render(request, "analyses/dashboard.html", {
        "actions": actions,
        "states": states,
        "recent": AnalysisJob.objects.select_related("user")[:8],
        "job_total": sum(state_counts.values()),
        "prediction_total": sum(action_counts.values()),
        "action_max": max(1, *(value for _, value in actions)),
        "state_max": max(1, *(value for _, value in states)),
    })
