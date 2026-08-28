class JobOffer:
    def __init__(self, id, source, url, time_posted, contract_type, title = "", company = "", localisation = "", contract_length = "", description = None, published_date = None, experience = None, diploma = []):
        self.id = id
        self.source = source
        self.title = title
        self.company = company
        self.url = url
        self.localisation = localisation
        self.contract_type = contract_type
        self.contract_length = contract_length
        self.time_posted = time_posted
        self.description = description
        self.published_date = published_date
        self.experience = experience
        self.diploma = diploma


    def to_dict(self):
        return {
            "id": self.id,
            "source": self.source,
            "title": self.title,
            "company": self.company,
            "url": self.url,
            "localisation": self.localisation,
            "contract_type": self.contract_type,
            "contract_length": self.contract_length,
            "time_posted": self.time_posted,
            "description": self.description,
            "published_date": self.published_date,
            "experience": self.experience,
            "diploma": self.diploma
        }


    def __repr__(self):
        return (
            f"JobOffer(id='{self.id}', "
            f"source='{self.source}', "
            f"title='{self.title}', "
            f"company='{self.company}', "
            f"url='{self.url}', "
            f"localisation='{self.localisation}', "
            f"contract_type='{self.contract_type}', "
            f"contract_length='{self.contract_length}', "
            f"time_posted='{self.time_posted}', "
            f"description='{self.description}', "
            f"published_date='{self.published_date}', "
            f"experience='{self.experience}', "
            f"diploma='{self.diploma}')"
        )
