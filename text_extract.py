#!/usr/bin/env python
import os
import csv
import click
import dj_database_url
import django
import scrapelib
from django.contrib.postgres.search import SearchVector

from extract.utils import jid_to_abbr, abbr_to_jid
from extract import extract_text

scraper = scrapelib.Scraper()

MIMETYPES = {
    "application/pdf": "pdf",
    "text/html": "html",
    "application/msword": "doc",
    "application/rtf": "rtf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx",
}


def init_django():
    from django.conf import settings

    DATABASE_URL = os.environ.get("DATABASE_URL", "postgis://localhost/openstatesorg")
    DATABASES = {"default": dj_database_url.parse(DATABASE_URL)}
    settings.configure(
        DATABASES=DATABASES, INSTALLED_APPS=("opencivicdata.core", "opencivicdata.legislative")
    )
    django.setup()


def download(version):
    abbr = jid_to_abbr(version["jurisdiction_id"])
    ext = MIMETYPES[version["media_type"]]
    filename = f'raw/{abbr}/{version["session"]}-{version["identifier"]}-{version["note"]}.{ext}'

    if not os.path.exists(filename):
        try:
            os.makedirs(os.path.dirname(filename))
        except OSError:
            pass
        try:
            _, resp = scraper.urlretrieve(version["url"], filename)
        except Exception:
            click.secho("could not fetch", version["url"], fg="yellow")
            return None, None

        return filename, resp.content
    else:
        with open(filename, "rb") as f:
            return filename, f.read()


def extract_to_file(filename, data, version):
    text = extract_text(data, version)

    if not text:
        return None, 0

    text_filename = filename.replace("raw/", "text/") + ".txt"
    try:
        os.makedirs(os.path.dirname(text_filename))
    except OSError:
        pass
    with open(text_filename, "w") as f:
        f.write(text)

    return text_filename, len(text)


def update_bill(bill):
    from opencivicdata.legislative.models import SearchableBill

    try:
        latest_version = bill.versions.order_by("-date", "-note").prefetch_related("links")[0]
    except IndexError:
        return

    # check if there's an old entry and we can use it
    # if bill.searchable:
    #     if bill.searchable.version_id == latest_version.id and not bill.searchable.is_error:
    #         return      # nothing to do
    #     bill.searchable.delete()

    # iterate through versions until we extract some good text
    is_error = True
    raw_text = ""
    for link in latest_version.links.all():
        try:
            data = scraper.get(link.url).content
        except Exception:
            continue
        metadata = {
            "url": link.url,
            "media_type": link.media_type,
            "title": bill.title,
            "jurisdiction_id": bill.legislative_session.jurisdiction_id,
        }
        # TODO: clean up whitespace
        try:
            raw_text = extract_text(data, metadata)
        except Exception as e:
            click.secho(e, fg="red")
            continue

        if raw_text:
            is_error = False
            break

    sb = SearchableBill.objects.create(
        bill=bill,
        version_link=link,
        all_titles=bill.title,  # TODO: add other titles
        raw_text=raw_text,
        is_error=is_error,
        search_vector="",
    )
    return sb.id


@click.group()
def cli():
    pass


@cli.command()
@click.argument("state")
def stats(state):
    init_django()
    from opencivicdata.legislative.models import Bill

    all_bills = Bill.objects.filter(legislative_session__jurisdiction__name=state)
    missing_search = Bill.objects.filter(
        legislative_session__jurisdiction__name=state, searchable__isnull=True
    )

    print(f"{state} is missing text for {missing_search.count()} out of {all_bills.count()}")


def _resample(state, n=50):
    """
    Grab new versions for a state from the database.
    """
    init_django()
    from opencivicdata.legislative.models import BillVersion

    versions = BillVersion.objects.filter(
        bill__legislative_session__jurisdiction_id=abbr_to_jid(state)
    ).order_by("?")[:n]

    count = 0
    fieldnames = [
        "id",
        "session",
        "identifier",
        "title",
        "jurisdiction_id",
        "media_type",
        "url",
        "note",
    ]

    with open(f"raw/{state}.csv", "w") as outf:
        out = csv.DictWriter(outf, fieldnames=fieldnames)
        out.writeheader()
        for v in versions:
            for link in v.links.all():
                out.writerow(
                    {
                        "id": v.id,
                        "session": v.bill.legislative_session.identifier,
                        "jurisdiction_id": v.bill.legislative_session.jurisdiction_id,
                        "identifier": v.bill.identifier,
                        "title": v.bill.title,
                        "url": link.url,
                        "media_type": link.media_type,
                        "note": v.note,
                    }
                )
                count += 1
    click.secho(f"wrote new sample csv with {count} records")


@cli.command()
@click.argument("state")
@click.option("--resample/--no-resample", default=False)
@click.option("--quiet/--no-quiet", default=False)
def sample(state, resample, quiet):
    if resample:
        _resample(state)
    count = missing = empty = 0
    with open(f"raw/{state}.csv") as f:
        for version in csv.DictReader(f):
            count += 1
            filename, data = download(version)
            if not filename:
                missing += 1
                continue
            text_filename, n_bytes = extract_to_file(filename, data, version)
            if not n_bytes:
                empty += 1
            if not quiet:
                click.secho(f"{filename} => {text_filename} ({n_bytes} bytes)")
    # decide and print result
    status = "green"
    if empty or missing > 10:  # arbitrary threshold for now
        status = "red"
    elif missing:
        status = "yellow"
    click.secho(f"processed {count}, {missing} missing, {empty} empty", fg=status)
    if status == "red":
        return 1


@cli.command()
@click.argument("state")
@click.option("-n", default=100)
def update(state, n):
    from opencivicdata.legislative.models import Bill, SearchableBill

    missing_search = Bill.objects.filter(
        legislative_session__jurisdiction_id=abbr_to_jid(state), searchable__isnull=True
    )[:n]
    print(f"selected {len(missing_search)} bills without search results for updating")

    ids_to_update = []
    for b in missing_search:
        ids_to_update.append(update_bill(b))

    print(f"updating {len(ids_to_update)} search vectors")
    SearchableBill.objects.filter(id__in=ids_to_update).update(
        search_vector=(
            SearchVector("all_titles", weight="A", config="english")
            + SearchVector("raw_text", weight="B", config="english")
        )
    )


if __name__ == "__main__":
    cli()
