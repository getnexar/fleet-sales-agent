"""
Cloud Storage service - loads FAQ knowledge base and agent instructions from GCS.
Allows updating content without redeployment.
"""
import json
import os
import logging
from typing import List, Dict, Optional
from google.cloud import storage

logger = logging.getLogger(__name__)

# Fallback: load from local config/ folder if GCS unavailable
LOCAL_CONFIG_DIR = os.path.join(os.path.dirname(__file__), "..", "config")


class StorageService:
    """Loads agent config (FAQs + instructions) from GCS bucket."""

    def __init__(self):
        self.bucket_name = os.environ.get("GCS_CONFIG_BUCKET", "fleet-sales-agent-config")
        self._faqs: Optional[List[Dict]] = None
        self._instructions: Optional[str] = None
        self._core_prompt: Optional[str] = None
        self._phase_prompts: Optional[Dict[str, str]] = None

        try:
            self.client = storage.Client()
            logger.info(f"GCS client initialized, bucket: {self.bucket_name}")
        except Exception as e:
            logger.warning(f"GCS unavailable, will use local config: {e}")
            self.client = None

    def get_faqs(self) -> List[Dict]:
        """Load FAQs from GCS (cached after first load)."""
        if self._faqs is not None:
            return self._faqs

        try:
            if self.client:
                bucket = self.client.bucket(self.bucket_name)
                blob = bucket.blob("faqs_core_28_final.json")
                content = blob.download_as_text()
                self._faqs = json.loads(content)
                logger.info(f"Loaded {len(self._faqs)} FAQs from GCS")
            else:
                raise Exception("No GCS client")
        except Exception as e:
            logger.warning(f"GCS load failed, using local FAQs: {e}")
            local_path = os.path.join(LOCAL_CONFIG_DIR, "faqs_core_28_final.json")
            with open(local_path, "r") as f:
                self._faqs = json.load(f)
            logger.info(f"Loaded {len(self._faqs)} FAQs from local config")

        return self._faqs

    def get_instructions(self) -> str:
        """Load agent instructions from GCS (cached after first load)."""
        if self._instructions is not None:
            return self._instructions

        try:
            if self.client:
                bucket = self.client.bucket(self.bucket_name)
                blob = bucket.blob("agent_instructions.md")
                self._instructions = blob.download_as_text()
                logger.info("Loaded agent instructions from GCS")
            else:
                raise Exception("No GCS client")
        except Exception as e:
            logger.warning(f"GCS load failed, using local instructions: {e}")
            local_path = os.path.join(LOCAL_CONFIG_DIR, "agent_instructions.md")
            with open(local_path, "r") as f:
                self._instructions = f.read()
            logger.info("Loaded agent instructions from local config")

        return self._instructions

    def get_core_prompt(self) -> Optional[str]:
        """Load core prompt from GCS. Returns None if not yet saved — caller uses hardcoded fallback."""
        if self._core_prompt is not None:
            return self._core_prompt
        try:
            if self.client:
                bucket = self.client.bucket(self.bucket_name)
                blob = bucket.blob("core_prompt.txt")
                if blob.exists():
                    self._core_prompt = blob.download_as_text()
                    logger.info("Loaded core prompt from GCS")
                    return self._core_prompt
        except Exception as e:
            logger.warning(f"GCS core prompt load failed: {e}")
        return None

    def get_phase_prompts(self) -> Optional[Dict[str, str]]:
        """Load phase prompts from GCS. Returns None if not yet saved — caller uses hardcoded fallback."""
        if self._phase_prompts is not None:
            return self._phase_prompts
        try:
            if self.client:
                bucket = self.client.bucket(self.bucket_name)
                blob = bucket.blob("phase_prompts.json")
                if blob.exists():
                    self._phase_prompts = json.loads(blob.download_as_text())
                    logger.info("Loaded phase prompts from GCS")
                    return self._phase_prompts
        except Exception as e:
            logger.warning(f"GCS phase prompts load failed: {e}")
        return None

    def save_faqs(self, faqs: List[Dict]) -> None:
        """Write FAQ JSON to GCS and invalidate cache."""
        if not self.client:
            raise RuntimeError("GCS client unavailable")
        bucket = self.client.bucket(self.bucket_name)
        bucket.blob("faqs_core_28_final.json").upload_from_string(
            json.dumps(faqs, indent=2), content_type="application/json"
        )
        self._faqs = None
        logger.info(f"Saved {len(faqs)} FAQs to GCS")

    def save_prompts(self, core_prompt: str, phase_prompts: Dict[str, str]) -> None:
        """Write core prompt and phase prompts to GCS and invalidate caches."""
        if not self.client:
            raise RuntimeError("GCS client unavailable")
        bucket = self.client.bucket(self.bucket_name)
        bucket.blob("core_prompt.txt").upload_from_string(core_prompt, content_type="text/plain")
        bucket.blob("phase_prompts.json").upload_from_string(
            json.dumps(phase_prompts, indent=2), content_type="application/json"
        )
        self._core_prompt = None
        self._phase_prompts = None
        logger.info("Saved prompts to GCS")

    def get_all_config(self) -> Dict:
        """Return all editable config (FAQs, core prompt, phase prompts)."""
        return {
            "faqs": self.get_faqs(),
            "core_prompt": self.get_core_prompt(),
            "phase_prompts": self.get_phase_prompts(),
        }

    def reload(self):
        """Force reload of config from GCS (clears all caches)."""
        self._faqs = None
        self._instructions = None
        self._core_prompt = None
        self._phase_prompts = None
        logger.info("Config cache cleared - will reload from GCS on next request")
