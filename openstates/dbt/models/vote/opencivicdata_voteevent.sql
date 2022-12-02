with opencivicdata_voteevent as (
    select created_at,
           updated_at,
           extras,
           id,
           identifier,
           motion_text,
           motion_classification,
           start_date,
           result,
           bill_id,
           bill_action_id,
           legislative_session_id,
           organization_id,
           "order",
           dedupe_key
           from opencivicdata_voteevent
)


select * from opencivicdata_voteevent