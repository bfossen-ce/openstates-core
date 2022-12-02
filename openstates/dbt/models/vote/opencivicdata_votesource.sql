with opencivicdata_votesource as (
    select id,
           note,
           url,
           vote_event_id
    from opencivicdata_votesource
)

select * from opencivicdata_votesource