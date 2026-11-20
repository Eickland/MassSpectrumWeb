"""
Схема БД.

projects ─┬─< samples ─┬─< spectra ─┬─< formulas
          │            │            └ qc / дескрипторы (JSON) + ключевые поля QC отдельными колонками
          │            └ метаданные лаб. журнала (место, даты, метод выделения, оператор …)
          └ описание, руководитель

У пробы может быть несколько загрузок спектра (переобработка, пересъёмка); актуальная — is_current = True,
старые остаются в истории. Формулы хранятся построчно: это позволяет сравнивать пробы и строить сводные
графики по проекту без чтения файлов.
"""
from datetime import date, datetime

from sqlalchemy import (JSON, Boolean, Date, DateTime, Float, ForeignKey, Index, Integer, String, Text,
                        UniqueConstraint, func)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


class Project(Base):
    __tablename__ = "projects"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200), unique=True, index=True)
    description: Mapped[str] = mapped_column(Text, default="")
    lead: Mapped[str] = mapped_column(String(200), default="")          # руководитель / ответственный
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    samples: Mapped[list["Sample"]] = relationship(back_populates="project")


class Sample(Base):
    __tablename__ = "samples"
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(200), unique=True, index=True)   # шифр = имя файла спектра
    project_id: Mapped[int | None] = mapped_column(ForeignKey("projects.id", ondelete="SET NULL"), index=True)
    group_label: Mapped[str] = mapped_column(String(100), default="")        # группа для статистики
    sample_type: Mapped[str] = mapped_column(String(100), default="")        # вода, почва, торф, препарат ГВ …
    location: Mapped[str] = mapped_column(String(300), default="")
    sampling_date: Mapped[date | None] = mapped_column(Date)
    extraction: Mapped[str] = mapped_column(String(200), default="")         # SPE PPL, …
    measured_at: Mapped[date | None] = mapped_column(Date)                   # дата съёмки спектра
    operator: Mapped[str] = mapped_column(String(200), default="")
    description: Mapped[str] = mapped_column(Text, default="")
    notes: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    project: Mapped[Project | None] = relationship(back_populates="samples")
    spectra: Mapped[list["Spectrum"]] = relationship(back_populates="sample", cascade="all, delete-orphan",
                                                     order_by="Spectrum.uploaded_at.desc()")

    @property
    def current(self) -> "Spectrum | None":
        return next((s for s in self.spectra if s.is_current), None)


class Spectrum(Base):
    __tablename__ = "spectra"
    id: Mapped[int] = mapped_column(primary_key=True)
    sample_id: Mapped[int] = mapped_column(ForeignKey("samples.id", ondelete="CASCADE"), index=True)
    is_current: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    uploaded_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), index=True)
    source_name: Mapped[str] = mapped_column(String(300), default="")        # имя пробы в конвейере / файла
    sha256: Mapped[str] = mapped_column(String(64), default="", index=True)  # хэш CSV формул
    # ключевые показатели (для реестра без разбора JSON)
    n_formulas: Mapped[int] = mapped_column(Integer, default=0)
    quality: Mapped[str] = mapped_column(String(50), default="")             # good / reduced mass accuracy / poor
    n_peaks: Mapped[int | None] = mapped_column(Integer)
    assign_tol_ppm: Mapped[float | None] = mapped_column(Float)
    sigma_strong_ppm: Mapped[float | None] = mapped_column(Float)
    final_err_rms_ppm: Mapped[float | None] = mapped_column(Float)
    calib_rms_ppm: Mapped[float | None] = mapped_column(Float)
    c13_confirmed_pct: Mapped[float | None] = mapped_column(Float)
    mz_min: Mapped[float | None] = mapped_column(Float)
    mz_max: Mapped[float | None] = mapped_column(Float)
    qc: Mapped[dict] = mapped_column(JSON, default=dict)                      # qc/<проба>.json без descriptors
    params: Mapped[dict] = mapped_column(JSON, default=dict)                  # PipelineParams
    descriptors: Mapped[dict] = mapped_column(JSON, default=dict)             # sample_descriptors (пересчёт сервером)

    sample: Mapped[Sample] = relationship(back_populates="spectra")
    formulas: Mapped[list["Formula"]] = relationship(back_populates="spectrum", cascade="all, delete-orphan",
                                                     passive_deletes=True)


class Formula(Base):
    __tablename__ = "formulas"
    id: Mapped[int] = mapped_column(primary_key=True)
    spectrum_id: Mapped[int] = mapped_column(ForeignKey("spectra.id", ondelete="CASCADE"))
    formula: Mapped[str] = mapped_column(String(64))
    C: Mapped[int] = mapped_column(Integer)
    H: Mapped[int] = mapped_column(Integer)
    O: Mapped[int] = mapped_column(Integer)
    N: Mapped[int] = mapped_column(Integer, default=0)
    S: Mapped[int] = mapped_column(Integer, default=0)
    theo_mz: Mapped[float] = mapped_column(Float)
    mz_cal: Mapped[float | None] = mapped_column(Float)
    err_ppm: Mapped[float | None] = mapped_column(Float)
    intensity: Mapped[float] = mapped_column(Float)
    rel_intensity: Mapped[float] = mapped_column(Float)
    sn: Mapped[float | None] = mapped_column(Float)
    elemental_class: Mapped[str] = mapped_column(String(8))
    hc: Mapped[float] = mapped_column(Float)
    oc: Mapped[float] = mapped_column(Float)
    dbe: Mapped[float] = mapped_column(Float)
    dbe_o: Mapped[float] = mapped_column(Float)
    ai_mod: Mapped[float] = mapped_column(Float)
    nosc: Mapped[float] = mapped_column(Float)
    cram: Mapped[bool] = mapped_column(Boolean, default=False)
    lasz_class: Mapped[str] = mapped_column(String(20), default="")
    square: Mapped[str] = mapped_column(String(4), default="")

    spectrum: Mapped[Spectrum] = relationship(back_populates="formulas")
    __table_args__ = (UniqueConstraint("spectrum_id", "formula"), Index("ix_formulas_formula", "formula"))
