"""Document chunking for policy and compliance data.

Chunks JSON policy/compliance documents into semantic units suitable for embedding
and retrieval.
"""

import json
import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional


@dataclass
class ChunkMetadata:
    """Metadata for a document chunk."""
    
    source_file: str
    state: str
    jurisdiction: str
    data_type: str  # "policy_language" or "compliance"
    section: str
    subsection: Optional[str] = None
    provision_id: Optional[str] = None
    title: Optional[str] = None
    is_state_specific: bool = False
    version: Optional[str] = None
    
    def to_dict(self) -> dict:
        """Convert metadata to dictionary."""
        return {
            "source_file": self.source_file,
            "state": self.state,
            "jurisdiction": self.jurisdiction,
            "data_type": self.data_type,
            "section": self.section,
            "subsection": self.subsection,
            "provision_id": self.provision_id,
            "title": self.title,
            "is_state_specific": self.is_state_specific,
            "version": self.version,
        }


@dataclass
class Chunk:
    """A document chunk with content and metadata."""
    
    content: str
    metadata: ChunkMetadata
    chunk_id: str = field(default="")
    
    def __post_init__(self):
        """Generate chunk ID from content hash if not provided."""
        if not self.chunk_id:
            content_hash = hashlib.md5(self.content.encode()).hexdigest()[:12]
            self.chunk_id = f"{self.metadata.state}-{self.metadata.section}-{content_hash}"
    
    def to_dict(self) -> dict:
        """Convert chunk to dictionary."""
        return {
            "chunk_id": self.chunk_id,
            "content": self.content,
            "metadata": self.metadata.to_dict(),
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> "Chunk":
        """Create chunk from dictionary."""
        metadata = ChunkMetadata(**data["metadata"])
        return cls(
            content=data["content"],
            metadata=metadata,
            chunk_id=data.get("chunk_id", ""),
        )


class DocumentChunker:
    """Chunks policy and compliance documents into semantic units."""
    
    # Maximum characters per chunk for context window management
    MAX_CHUNK_SIZE = 2000
    
    def __init__(self, max_chunk_size: int = MAX_CHUNK_SIZE):
        self.max_chunk_size = max_chunk_size
    
    def chunk_json_document(self, file_path: Path) -> list[Chunk]:
        """Load and chunk a JSON document based on its type.
        
        Args:
            file_path: Path to the JSON file
            
        Returns:
            List of Chunk objects
        """
        with open(file_path) as f:
            data = json.load(f)
        
        source_file = file_path.name
        metadata_section = data.get("metadata", {})
        data_type = metadata_section.get("data_type", "unknown")
        
        if "compliance" in data_type.lower():
            return self._chunk_compliance_document(data, source_file)
        elif "policy_language" in data_type.lower():
            return self._chunk_policy_document(data, source_file)
        else:
            # Generic chunking
            return self._chunk_generic_document(data, source_file)
    
    def _chunk_policy_document(self, data: dict, source_file: str) -> list[Chunk]:
        """Chunk a policy language document."""
        chunks = []
        metadata_section = data.get("metadata", {})
        state = metadata_section.get("state", "Unknown")
        jurisdiction = metadata_section.get("jurisdiction", "")
        version = metadata_section.get("version", "")
        
        # Skip metadata section, process other sections
        for section_name, section_data in data.items():
            if section_name == "metadata":
                continue
            
            if isinstance(section_data, dict):
                chunks.extend(
                    self._chunk_policy_section(
                        section_name, section_data, source_file, 
                        state, jurisdiction, version
                    )
                )
        
        return chunks
    
    def _chunk_policy_section(
        self, 
        section_name: str, 
        section_data: dict,
        source_file: str,
        state: str,
        jurisdiction: str,
        version: str,
    ) -> list[Chunk]:
        """Chunk a policy section into meaningful units."""
        chunks = []
        
        # Check for state-specific marker
        is_state_specific = section_data.get(f"{state.lower()}_specific", False) or \
                           section_data.get("california_specific", False) or \
                           section_data.get("texas_specific", False) or \
                           section_data.get("florida_specific", False)
        
        section_title = section_data.get("section_title", section_name)
        description = section_data.get("description", "")
        
        # Process different content types within a section
        
        # 1. Insuring agreement
        if "insuring_agreement" in section_data:
            agreement = section_data["insuring_agreement"]
            content = self._format_insuring_agreement(section_title, agreement)
            chunks.append(self._create_chunk(
                content=content,
                source_file=source_file,
                state=state,
                jurisdiction=jurisdiction,
                data_type="policy_language",
                section=section_name,
                subsection="insuring_agreement",
                title=f"{section_title} - Insuring Agreement",
                is_state_specific=is_state_specific or agreement.get(f"{state.lower()}_specific", False),
                version=version,
            ))
        
        # 2. Exclusions
        if "exclusions" in section_data:
            exclusions = section_data["exclusions"]
            for exclusion in exclusions.get("exclusion_list", []):
                content = self._format_exclusion(section_title, exclusion)
                chunks.append(self._create_chunk(
                    content=content,
                    source_file=source_file,
                    state=state,
                    jurisdiction=jurisdiction,
                    data_type="policy_language",
                    section=section_name,
                    subsection="exclusion",
                    provision_id=exclusion.get("id"),
                    title=exclusion.get("title"),
                    is_state_specific=exclusion.get(f"{state.lower()}_specific", False),
                    version=version,
                ))
        
        # 3. Definitions
        if "terms" in section_data:
            for term_def in section_data["terms"]:
                content = self._format_definition(term_def)
                is_term_state_specific = term_def.get(f"{state.lower()}_specific", False) or \
                                         term_def.get("florida_specific", False) or \
                                         term_def.get("texas_specific", False)
                chunks.append(self._create_chunk(
                    content=content,
                    source_file=source_file,
                    state=state,
                    jurisdiction=jurisdiction,
                    data_type="policy_language",
                    section="definitions",
                    subsection="term",
                    title=term_def.get("term"),
                    is_state_specific=is_term_state_specific,
                    version=version,
                ))
        
        # 4. Provisions/general content
        if "provisions" in section_data:
            for provision in section_data["provisions"]:
                content = self._format_provision(provision)
                chunks.append(self._create_chunk(
                    content=content,
                    source_file=source_file,
                    state=state,
                    jurisdiction=jurisdiction,
                    data_type="policy_language",
                    section=section_name,
                    subsection="provision",
                    title=provision.get("title"),
                    is_state_specific=provision.get(f"{state.lower()}_specific", False),
                    version=version,
                ))
        
        # 5. Endorsements
        if "endorsements" in section_data:
            for endorsement in section_data["endorsements"]:
                content = self._format_endorsement(endorsement)
                chunks.append(self._create_chunk(
                    content=content,
                    source_file=source_file,
                    state=state,
                    jurisdiction=jurisdiction,
                    data_type="policy_language",
                    section=section_name,
                    subsection="endorsement",
                    provision_id=endorsement.get("id"),
                    title=endorsement.get("title"),
                    is_state_specific=True,  # Endorsements are typically state-specific
                    version=version,
                ))
        
        # 6. Sample language
        if "sample_language" in section_data:
            for key, value in section_data["sample_language"].items():
                if isinstance(value, str):
                    content = f"[{section_title}] {key}: {value}"
                    chunks.append(self._create_chunk(
                        content=content,
                        source_file=source_file,
                        state=state,
                        jurisdiction=jurisdiction,
                        data_type="policy_language",
                        section=section_name,
                        subsection="sample_language",
                        title=key,
                        is_state_specific=key.endswith("_specific"),
                        version=version,
                    ))
        
        # 7. Limit of liability
        if "limit_of_liability" in section_data:
            lol = section_data["limit_of_liability"]
            content = f"[{section_title}] Limit of Liability: {lol.get('language', '')}"
            chunks.append(self._create_chunk(
                content=content,
                source_file=source_file,
                state=state,
                jurisdiction=jurisdiction,
                data_type="policy_language",
                section=section_name,
                subsection="limit_of_liability",
                title="Limit of Liability",
                is_state_specific=is_state_specific,
                version=version,
            ))
        
        # 8. General language fields
        if "language" in section_data and isinstance(section_data["language"], str):
            content = f"[{section_title}] {section_data['language']}"
            chunks.append(self._create_chunk(
                content=content,
                source_file=source_file,
                state=state,
                jurisdiction=jurisdiction,
                data_type="policy_language",
                section=section_name,
                title=section_title,
                is_state_specific=is_state_specific,
                version=version,
            ))
        
        return chunks
    
    def _chunk_compliance_document(self, data: dict, source_file: str) -> list[Chunk]:
        """Chunk a compliance/regulatory document."""
        chunks = []
        metadata_section = data.get("metadata", {})
        state = metadata_section.get("state", "Unknown")
        jurisdiction = metadata_section.get("jurisdiction", "")
        version = metadata_section.get("version", "")
        
        for section_name, section_data in data.items():
            if section_name == "metadata":
                continue
            
            if isinstance(section_data, dict):
                chunks.extend(
                    self._chunk_compliance_section(
                        section_name, section_data, source_file,
                        state, jurisdiction, version
                    )
                )
        
        return chunks
    
    def _chunk_compliance_section(
        self,
        section_name: str,
        section_data: dict,
        source_file: str,
        state: str,
        jurisdiction: str,
        version: str,
    ) -> list[Chunk]:
        """Chunk a compliance section."""
        chunks = []
        
        reg_reference = section_data.get("regulation_reference", "")
        description = section_data.get("description", "")
        
        # 1. Provisions
        if "provisions" in section_data:
            for provision in section_data["provisions"]:
                content = self._format_compliance_provision(
                    section_name, reg_reference, provision
                )
                chunks.append(self._create_chunk(
                    content=content,
                    source_file=source_file,
                    state=state,
                    jurisdiction=jurisdiction,
                    data_type="compliance",
                    section=section_name,
                    subsection="provision",
                    provision_id=provision.get("id"),
                    title=provision.get("title"),
                    is_state_specific=True,
                    version=version,
                ))
        
        # 2. Deadlines
        if "deadlines" in section_data:
            for deadline in section_data["deadlines"]:
                content = self._format_deadline(section_name, deadline)
                chunks.append(self._create_chunk(
                    content=content,
                    source_file=source_file,
                    state=state,
                    jurisdiction=jurisdiction,
                    data_type="compliance",
                    section=section_name,
                    subsection="deadline",
                    provision_id=deadline.get("id"),
                    title=deadline.get("action"),
                    is_state_specific=True,
                    version=version,
                ))
        
        # 3. Disclosures
        if "disclosures" in section_data:
            for disclosure in section_data["disclosures"]:
                content = self._format_disclosure(disclosure)
                chunks.append(self._create_chunk(
                    content=content,
                    source_file=source_file,
                    state=state,
                    jurisdiction=jurisdiction,
                    data_type="compliance",
                    section=section_name,
                    subsection="disclosure",
                    provision_id=disclosure.get("id"),
                    title=disclosure.get("title"),
                    is_state_specific=True,
                    version=version,
                ))
        
        # 4. Prohibited practices
        if "prohibited_practices" in section_data:
            for practice in section_data["prohibited_practices"]:
                content = self._format_prohibited_practice(practice)
                chunks.append(self._create_chunk(
                    content=content,
                    source_file=source_file,
                    state=state,
                    jurisdiction=jurisdiction,
                    data_type="compliance",
                    section=section_name,
                    subsection="prohibited_practice",
                    provision_id=practice.get("id"),
                    title=practice.get("title"),
                    is_state_specific=True,
                    version=version,
                ))
        
        # 5. Requirements
        if "requirements" in section_data:
            for req in section_data["requirements"]:
                content = self._format_requirement(section_name, req)
                chunks.append(self._create_chunk(
                    content=content,
                    source_file=source_file,
                    state=state,
                    jurisdiction=jurisdiction,
                    data_type="compliance",
                    section=section_name,
                    subsection="requirement",
                    provision_id=req.get("id"),
                    title=req.get("coverage_type", req.get("title")),
                    is_state_specific=True,
                    version=version,
                ))
        
        # 6. Limitations (statute of limitations)
        if "limitations" in section_data:
            for limitation in section_data["limitations"]:
                content = self._format_limitation(limitation)
                chunks.append(self._create_chunk(
                    content=content,
                    source_file=source_file,
                    state=state,
                    jurisdiction=jurisdiction,
                    data_type="compliance",
                    section=section_name,
                    subsection="limitation",
                    title=limitation.get("action"),
                    is_state_specific=True,
                    version=version,
                ))
        
        # 7. Scenarios
        if "scenarios" in section_data:
            for scenario in section_data["scenarios"]:
                content = self._format_scenario(scenario)
                chunks.append(self._create_chunk(
                    content=content,
                    source_file=source_file,
                    state=state,
                    jurisdiction=jurisdiction,
                    data_type="compliance",
                    section=section_name,
                    subsection="scenario",
                    provision_id=scenario.get("id"),
                    title=scenario.get("scenario"),
                    is_state_specific=True,
                    version=version,
                ))
        
        # 8. Section description as a chunk
        if description:
            content = f"[{section_name}] {description}"
            if reg_reference:
                content = f"[{section_name}] (Ref: {reg_reference}) {description}"
            chunks.append(self._create_chunk(
                content=content,
                source_file=source_file,
                state=state,
                jurisdiction=jurisdiction,
                data_type="compliance",
                section=section_name,
                title=section_name,
                is_state_specific=True,
                version=version,
            ))
        
        return chunks
    
    def _chunk_generic_document(self, data: dict, source_file: str) -> list[Chunk]:
        """Generic chunking for unknown document types."""
        chunks = []
        metadata_section = data.get("metadata", {})
        state = metadata_section.get("state", "Unknown")
        jurisdiction = metadata_section.get("jurisdiction", "")
        version = metadata_section.get("version", "")
        data_type = metadata_section.get("data_type", "unknown")
        
        # Convert entire document to string and chunk by size
        content = json.dumps(data, indent=2)
        
        # Simple chunking by character limit
        for i in range(0, len(content), self.max_chunk_size):
            chunk_content = content[i:i + self.max_chunk_size]
            chunks.append(self._create_chunk(
                content=chunk_content,
                source_file=source_file,
                state=state,
                jurisdiction=jurisdiction,
                data_type=data_type,
                section=f"chunk_{i // self.max_chunk_size}",
                version=version,
            ))
        
        return chunks
    
    def _create_chunk(
        self,
        content: str,
        source_file: str,
        state: str,
        jurisdiction: str,
        data_type: str,
        section: str,
        subsection: Optional[str] = None,
        provision_id: Optional[str] = None,
        title: Optional[str] = None,
        is_state_specific: bool = False,
        version: Optional[str] = None,
    ) -> Chunk:
        """Create a Chunk with metadata."""
        metadata = ChunkMetadata(
            source_file=source_file,
            state=state,
            jurisdiction=jurisdiction,
            data_type=data_type,
            section=section,
            subsection=subsection,
            provision_id=provision_id,
            title=title,
            is_state_specific=is_state_specific,
            version=version,
        )
        return Chunk(content=content, metadata=metadata)
    
    # Formatting helpers
    
    def _format_insuring_agreement(self, section_title: str, agreement: dict) -> str:
        """Format an insuring agreement for chunking."""
        title = agreement.get("title", "Insuring Agreement")
        language = agreement.get("language", "")
        return f"[{section_title}] {title}: {language}"
    
    def _format_exclusion(self, section_title: str, exclusion: dict) -> str:
        """Format an exclusion for chunking."""
        excl_id = exclusion.get("id", "")
        title = exclusion.get("title", "")
        language = exclusion.get("language", "")
        return f"[{section_title}] Exclusion {excl_id} - {title}: {language}"
    
    def _format_definition(self, term_def: dict) -> str:
        """Format a definition for chunking."""
        term = term_def.get("term", "")
        definition = term_def.get("definition", "")
        return f"[Definition] {term}: {definition}"
    
    def _format_provision(self, provision: dict) -> str:
        """Format a general provision for chunking."""
        title = provision.get("title", "")
        language = provision.get("language", "")
        return f"[Provision] {title}: {language}"
    
    def _format_endorsement(self, endorsement: dict) -> str:
        """Format an endorsement for chunking."""
        form_number = endorsement.get("form_number", "")
        title = endorsement.get("title", "")
        description = endorsement.get("description", "")
        language = endorsement.get("language", "")
        return f"[Endorsement {form_number}] {title}: {description}. {language}"
    
    def _format_compliance_provision(
        self, section_name: str, reg_reference: str, provision: dict
    ) -> str:
        """Format a compliance provision for chunking."""
        prov_id = provision.get("id", "")
        prov_section = provision.get("section", "")
        title = provision.get("title", "")
        requirement = provision.get("requirement", "")
        time_limit = provision.get("time_limit_days")
        
        content = f"[{section_name}] {prov_id} - {title}"
        if prov_section:
            content += f" ({prov_section})"
        content += f": {requirement}"
        if time_limit:
            content += f" [Time Limit: {time_limit} days]"
        return content
    
    def _format_deadline(self, section_name: str, deadline: dict) -> str:
        """Format a deadline for chunking."""
        dl_id = deadline.get("id", "")
        action = deadline.get("action", "")
        time_limit = deadline.get("time_limit", "")
        reference = deadline.get("reference", "")
        return f"[{section_name}] Deadline {dl_id}: {action} - {time_limit}. Ref: {reference}"
    
    def _format_disclosure(self, disclosure: dict) -> str:
        """Format a disclosure requirement for chunking."""
        disc_id = disclosure.get("id", "")
        title = disclosure.get("title", "")
        requirement = disclosure.get("requirement", "")
        content_includes = disclosure.get("content_includes", [])
        
        content = f"[Required Disclosure] {disc_id} - {title}: {requirement}"
        if content_includes:
            content += f" Includes: {', '.join(content_includes)}"
        return content
    
    def _format_prohibited_practice(self, practice: dict) -> str:
        """Format a prohibited practice for chunking."""
        prac_id = practice.get("id", "")
        title = practice.get("title", "")
        description = practice.get("description", "")
        reference = practice.get("reference", "")
        return f"[Prohibited Practice] {prac_id} - {title}: {description}. Ref: {reference}"
    
    def _format_requirement(self, section_name: str, req: dict) -> str:
        """Format a requirement for chunking."""
        req_id = req.get("id", "")
        coverage_type = req.get("coverage_type", req.get("title", ""))
        minimum = req.get("minimum_limit", "")
        description = req.get("description", req.get("requirement", ""))
        
        content = f"[{section_name}] {req_id} - {coverage_type}"
        if minimum:
            content += f" (Minimum: {minimum})"
        content += f": {description}"
        return content
    
    def _format_limitation(self, limitation: dict) -> str:
        """Format a statute of limitations for chunking."""
        action = limitation.get("action", "")
        time_limit = limitation.get("time_limit", "")
        reference = limitation.get("reference", "")
        return f"[Statute of Limitations] {action}: {time_limit}. Ref: {reference}"
    
    def _format_scenario(self, scenario: dict) -> str:
        """Format a claim scenario for chunking."""
        scen_id = scenario.get("id", "")
        scenario_name = scenario.get("scenario", "")
        presumption = scenario.get("presumption", scenario.get("rule", ""))
        exceptions = scenario.get("exceptions", "")
        
        content = f"[Claim Scenario] {scen_id} - {scenario_name}: {presumption}"
        if exceptions:
            content += f" Exceptions: {exceptions}"
        return content


def chunk_policy_data(data_dir: Path) -> list[Chunk]:
    """Chunk all policy language files in a directory.
    
    Args:
        data_dir: Path to the data directory
        
    Returns:
        List of all chunks from policy language files
    """
    chunker = DocumentChunker()
    all_chunks = []
    
    for file_path in data_dir.glob("*_policy_language.json"):
        chunks = chunker.chunk_json_document(file_path)
        all_chunks.extend(chunks)
    
    return all_chunks


def chunk_compliance_data(data_dir: Path) -> list[Chunk]:
    """Chunk all compliance files in a directory.
    
    Args:
        data_dir: Path to the data directory
        
    Returns:
        List of all chunks from compliance files
    """
    chunker = DocumentChunker()
    all_chunks = []
    
    for file_path in data_dir.glob("*_compliance.json"):
        chunks = chunker.chunk_json_document(file_path)
        all_chunks.extend(chunks)
    
    return all_chunks
