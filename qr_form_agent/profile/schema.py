"""Pydantic schemas for verified candidate profile.

All fields are strictly nullable. The rule is: 'null if absent, never guess'.
"""

from typing import Any, Dict, List, Optional
from pydantic import BaseModel, EmailStr, Field


class LinkItem(BaseModel):
    label: str = Field(description="Type or label of the link, e.g. LinkedIn, GitHub, Portfolio")
    url: str = Field(description="Target URL")


class EducationItem(BaseModel):
    institution: Optional[str] = Field(default=None, description="University, college, or school name")
    degree: Optional[str] = Field(default=None, description="Degree or certification earned, e.g. Bachelor of Science")
    field_of_study: Optional[str] = Field(default=None, description="Major, field, or concentration")
    start_year: Optional[str] = Field(default=None, description="Start year or date")
    end_year: Optional[str] = Field(default=None, description="Graduation year or date")
    gpa: Optional[str] = Field(default=None, description="GPA or honors if explicitly specified")


class ExperienceItem(BaseModel):
    company: Optional[str] = Field(default=None, description="Employer or company name")
    title: Optional[str] = Field(default=None, description="Job title / role")
    location: Optional[str] = Field(default=None, description="Office location or Remote status")
    start_date: Optional[str] = Field(default=None, description="Start date, e.g. 05/2021")
    end_date: Optional[str] = Field(default=None, description="End date, or Present")
    is_current: Optional[bool] = Field(default=None, description="True if currently employed here")
    description: Optional[str] = Field(default=None, description="Bullet points or summary of duties and impact")


class ProjectItem(BaseModel):
    name: Optional[str] = Field(default=None, description="Project title")
    description: Optional[str] = Field(default=None, description="Overview of the project")
    technologies: List[str] = Field(default_factory=list, description="Technologies or tools used")
    link: Optional[str] = Field(default=None, description="URL to repository, demo, or publication")


class Profile(BaseModel):
    """
    Candidate profile extracted from resume.
    All attributes are nullable - must never be hallucinated or guessed.
    """
    full_name: Optional[str] = Field(default=None, description="Full legal or professional name")
    first_name: Optional[str] = Field(default=None, description="Given / first name")
    last_name: Optional[str] = Field(default=None, description="Family / last name")
    email: Optional[str] = Field(default=None, description="Email address")
    phone: Optional[str] = Field(default=None, description="Phone number with country code")

    # Location
    address: Optional[str] = Field(default=None, description="Street address")
    city: Optional[str] = Field(default=None, description="City")
    state: Optional[str] = Field(default=None, description="State, province, or region")
    postal_code: Optional[str] = Field(default=None, description="ZIP / Postal code")
    country: Optional[str] = Field(default=None, description="Country")

    # Online Presence
    linkedin_url: Optional[str] = Field(default=None, description="LinkedIn profile URL")
    github_url: Optional[str] = Field(default=None, description="GitHub profile URL")
    portfolio_url: Optional[str] = Field(default=None, description="Personal website or portfolio URL")
    other_links: List[LinkItem] = Field(default_factory=list, description="Other verified external links")

    # Summary & Work Authorization
    summary: Optional[str] = Field(default=None, description="Professional summary / objective")
    work_authorization: Optional[str] = Field(default=None, description="Work authorization status if explicitly stated")
    requires_sponsorship: Optional[bool] = Field(default=None, description="True if visa sponsorship needed, null if unknown")

    # History & Skills
    education: List[EducationItem] = Field(default_factory=list, description="Educational background")
    experience: List[ExperienceItem] = Field(default_factory=list, description="Work experience items")
    skills: List[str] = Field(default_factory=list, description="List of verified skills")
    projects: List[ProjectItem] = Field(default_factory=list, description="Projects highlighted in resume")

    # Attachment tracking
    resume_file_path: Optional[str] = Field(default=None, description="Local filesystem path to original resume file")

    def to_flat_dict(self) -> Dict[str, Any]:
        """
        Produce a flat dictionary of simple key-value pairs suitable for
        deterministic matching and LLM mapping context.
        """
        flat: Dict[str, Any] = {
            "full_name": self.full_name,
            "first_name": self.first_name,
            "last_name": self.last_name,
            "email": self.email,
            "phone": self.phone,
            "address": self.address,
            "city": self.city,
            "state": self.state,
            "postal_code": self.postal_code,
            "country": self.country,
            "linkedin_url": self.linkedin_url,
            "github_url": self.github_url,
            "portfolio_url": self.portfolio_url,
            "summary": self.summary,
            "skills": ", ".join(self.skills) if self.skills else None,
        }

        if self.education:
            latest_edu = self.education[0]
            flat["university"] = latest_edu.institution
            flat["degree"] = latest_edu.degree
            flat["major"] = latest_edu.field_of_study
            flat["gpa"] = latest_edu.gpa
            flat["grad_year"] = latest_edu.end_year

        if self.experience:
            latest_exp = self.experience[0]
            flat["current_company"] = latest_exp.company
            flat["current_title"] = latest_exp.title
            flat["work_history_summary"] = f"{latest_exp.title} at {latest_exp.company}"

        return flat
