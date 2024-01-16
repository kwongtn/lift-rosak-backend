from collections import defaultdict

from strawberry.dataloader import DataLoader

from incident.models import CalendarIncidentMedia


async def batch_load_medias_from_calendar_incident(keys):
    incident_medias = CalendarIncidentMedia.objects.filter(
        calendar_incident_id__in=keys,
    ).select_related("media")

    incident_dict = defaultdict(set)
    async for incident_media in incident_medias:
        incident_dict[incident_media.calendar_incident_id].add(incident_media.media)

    return [incident_dict.get(key, set()) for key in keys]


IncidentContextLoaders = {
    "medias_from_calendar_incident_loader": DataLoader(
        load_fn=batch_load_medias_from_calendar_incident
    ),
}
