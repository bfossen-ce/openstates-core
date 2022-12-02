with opencivicdata_votecount as (
    select id,
           option,
           value,
           vote_event_id
    from opencivicdata_votecount
)

select * from opencivicdata_votecount