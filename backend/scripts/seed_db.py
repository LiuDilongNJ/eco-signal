import logging
import random
from datetime import datetime, timedelta
from typing import List

from sqlmodel import Session, select

from app.core.db import engine
from app.core.security import get_password_hash
from app.models import (
    Annotation,
    AnnotationReview,
    AnnotationReviewStatus,
    AudioSetting,
    Collection,
    IndexLog,
    IndexType,
    License,
    Media,
    Microphone,
    Project,
    ProjectCollection,
    Queue,
    Recorder,
    Role,
    Sensor,
    Site,
    SiteProject,
    SoundClassification,
    Task,
    Taxon,
    User,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def rnd_date(days_back: int = 365) -> datetime:
    return datetime.utcnow() - timedelta(days=random.randint(0, days_back), seconds=random.randint(0, 86400))

def pick(lst: List):
    return random.choice(lst)

def seed_db():
    with Session(engine) as session:
        # 1. Roles (Ensure Admin and User exist)
        admin_role = session.exec(select(Role).where(Role.name == "admin")).first()
        if not admin_role:
            admin_role = Role(name="admin")
            session.add(admin_role)
        
        user_role = session.exec(select(Role).where(Role.name == "user")).first()
        if not user_role:
            user_role = Role(name="user")
            session.add(user_role)
        
        session.commit()
        session.refresh(admin_role)
        session.refresh(user_role)

        # 2. Users (50 users)
        users = []
        for i in range(50):
            username = f"user_{i+1}"
            existing = session.exec(select(User).where(User.username == username)).first()
            if not existing:
                u = User(
                    username=username,
                    name=f"Full Name {i+1}",
                    email=f"user{i+1}@example.com",
                    password=get_password_hash("password123"),
                    role_id=user_role.role_id,
                    active=True
                )
                session.add(u)
                users.append(u)
            else:
                users.append(existing)
        session.commit()
        for u in users:
            session.refresh(u)

        # 3. Projects (50 projects)
        projects = []
        for i in range(50):
            p = Project(
                name=f"Project {i+1}: {pick(['Bio-diversity', 'Eco-Signal', 'Forest Monitoring', 'Oceanic Survey'])}",
                url=f"http://project{i+1}.org",
                description=f"Detailed description for project {i+1}.",
                doi=f"10.1000/project.{i+1}",
                creator_id=pick(users).user_id,
                public=True,
                active=True
            )
            session.add(p)
            projects.append(p)
        session.commit()
        for p in projects:
            session.refresh(p)

        # 4. Collections (50 collections)
        collections = []
        for i in range(50):
            c = Collection(
                name=f"Collection {i+1}",
                sphere=pick(["Terrestrial", "Marine", "Freshwater"]),
                description=f"Data collection {i+1} from field survey.",
                creator_id=pick(users).user_id,
                public_access=True
            )
            session.add(c)
            collections.append(c)
        session.commit()
        for c in collections:
            session.refresh(c)

        # Link projects and collections
        for p in projects:
            pc = ProjectCollection(project_id=p.project_id, collection_id=pick(collections).collection_id)
            session.add(pc)
        session.commit()

        # 5. Sites (50 sites)
        sites = []
        for i in range(50):
            s = Site(
                name=f"Site {i+1} - {pick(['Ridge', 'Valley', 'Shore', 'Glade'])}",
                longitude=round(random.uniform(-180, 180), 6),
                latitude=round(random.uniform(-90, 90), 6),
                creator_id=pick(users).user_id,
                gadm0=pick(["Brazil", "Congo", "Indonesia", "Australia"]),
                gadm1=f"Province {i}",
                gadm2=f"District {i}"
            )
            session.add(s)
            sites.append(s)
        session.commit()
        for s in sites:
            session.refresh(s)

        # Link sites to projects
        for s in sites:
            sp = SiteProject(site_id=s.site_id, project_id=pick(projects).project_id)
            session.add(sp)
        session.commit()

        # 6. Licenses
        licenses = []
        for name, link in [("CC BY 4.0", "https://creativecommons.org/licenses/by/4.0/"), ("CC0 1.0", "https://creativecommons.org/publicdomain/zero/1.0/")]:
            lic = session.exec(select(License).where(License.name == name)).first()
            if not lic:
                lic = License(name=name, link=link)
                session.add(lic)
            licenses.append(lic)
        session.commit()
        for l in licenses:
            session.refresh(l)

        # 7. Devices (Recorders & Microphones)
        recorders = []
        for i in range(10):
            r = Recorder(name=f"Recorder {i+1}", brand=pick(["Sony", "Zoom", "AudioMoth"]), version="v2.0")
            session.add(r)
            recorders.append(r)
        
        microphones = []
        for i in range(10):
            m = Microphone(name=f"Mic {i+1}", microphone_element="Condenser", sensitivity=-35)
            session.add(m)
            microphones.append(m)
        session.commit()
        for r in recorders: session.refresh(r)
        for m in microphones: session.refresh(m)

        sensors = []
        for i in range(10):
            sens = Sensor(name=f"Sensor {i+1}", sensor_type="audio", recorder_id=pick(recorders).recorder_id, microphone_id=pick(microphones).microphone_id)
            session.add(sens)
            sensors.append(sens)
        session.commit()
        for s in sensors: session.refresh(s)

        # 8. Media (Audios - 50 rows)
        media_list = []
        for i in range(50):
            # Create AudioSetting first
            audio_set = AudioSetting(sampling_rate_hz=pick([44100, 48000, 96000]), bit_depth=pick([16, 24]), duration_s=random.uniform(10.0, 300.0))
            session.add(audio_set)
            session.commit()
            session.refresh(audio_set)

            m = Media(
                media_type="audio",
                filename=f"recording_{i+1}.wav",
                name=f"Audio Recording {i+1}",
                uploader_id=pick(users).user_id,
                creator_id=pick(users).user_id,
                site_id=pick(sites).site_id,
                sensor_id=pick(sensors).sensor_id,
                license_id=pick(licenses).license_id,
                audio_setting_id=audio_set.audio_setting_id,
                date_time=rnd_date(),
                size_b=random.randint(1000000, 50000000)
            )
            session.add(m)
            media_list.append(m)
        session.commit()
        for m in media_list: session.refresh(m)

        # 9. Taxons (50 rows)
        taxons = []
        for i in range(50):
            t = Taxon(
                cached_scientific_name=f"Scientific Name {i+1}",
                cached_common_name=f"Common Name {i+1}",
                taxonomy_source="CatalogueOfLife",
                col_species_id=f"species_{i+1}",
                col_genus_id=f"genus_{i+1}",
                col_family_id=f"family_{i+1}",
                col_order_id=f"order_{i+1}",
                col_class_id=f"class_{i+1}"
            )
            session.add(t)
            taxons.append(t)
        session.commit()
        for t in taxons: session.refresh(t)

        # 10. Sound Classification & Annotations
        sound_class = session.exec(select(SoundClassification)).first()
        if not sound_class:
            sound_class = SoundClassification(soundscape_component="Biophony", sound_type="Vocalization")
            session.add(sound_class)
            session.commit()
            session.refresh(sound_class)

        review_status = session.exec(select(AnnotationReviewStatus)).first()
        if not review_status:
            review_status = AnnotationReviewStatus(name="needs_review")
            session.add(review_status)
            session.commit()
            session.refresh(review_status)

        annotations = []
        for i in range(50):
            ann = Annotation(
                media_id=pick(media_list).media_id,
                creator_id=pick(users).user_id,
                taxon_id=pick(taxons).taxon_id,
                sound_id=sound_class.sound_id,
                confidence=random.uniform(0.5, 0.99),
                min_x=0.0, max_x=10.0, min_y=0.0, max_y=5.0,
                comments=f"Automated annotation {i+1}"
            )
            session.add(ann)
            annotations.append(ann)
        session.commit()
        for a in annotations: session.refresh(a)

        # 11. Reviews (50 rows)
        for i in range(50):
            rev = AnnotationReview(
                annotation_id=pick(annotations).annotation_id,
                reviewer_id=pick(users).user_id,
                annotation_review_status_id=review_status.annotation_review_status_id,
                note=f"Review note {i+1}"
            )
            session.add(rev)
        session.commit()

        # 12. Tasks (50 rows)
        for i in range(50):
            task = Task(
                type=pick(["annotation", "review"]),
                media_id=pick(media_list).media_id,
                assigner_id=pick(users).user_id,
                assignee_id=pick(users).user_id,
                status=pick(["assigned", "completed"]),
                comment=f"Task instructions {i+1}"
            )
            session.add(task)
        session.commit()

        # 13. Queue (50 rows)
        for i in range(50):
            q = Queue(
                type=pick(["spectrogram", "index", "model_inference"]),
                user_id=pick(users).user_id,
                total=100,
                completed=random.randint(0, 100),
                status=pick([0, 1, 2, 3]),
                start_time=rnd_date()
            )
            session.add(q)
        session.commit()

        # 14. Index Logs (50 rows)
        idx_type = session.exec(select(IndexType)).first()
        if not idx_type:
            idx_type = IndexType(name="ACI", description="Acoustic Complexity Index")
            session.add(idx_type)
            session.commit()
            session.refresh(idx_type)

        for i in range(50):
            log = IndexLog(
                media_id=pick(media_list).media_id,
                user_id=pick(users).user_id,
                index_id=idx_type.index_id,
                variable_order=1,
                variable_name="mean",
                variable_value=str(round(random.uniform(0, 100), 2))
            )
            session.add(log)
        session.commit()

    logger.info("Successfully seeded 50 rows for each major module.")

if __name__ == "__main__":
    seed_db()
