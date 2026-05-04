from dataclasses import dataclass


@dataclass
class TrainingConfig:
    # Model
    model_name: str = "xlm-roberta-base"
    max_seq_length: int = 512
    max_seq_length_liar: int = 128

    # Task labels
    num_stance_labels: int = 4   # unrelated, discuss, agree, disagree
    num_fakenews_labels: int = 2 # binary: 0=False (fake), 1=True (real)

    # Training
    batch_size: int = 16
    learning_rate: float = 2e-5
    head_lr_multiplier: float = 10.0
    num_epochs: int = 5
    warmup_ratio: float = 0.1
    weight_decay: float = 0.01
    max_grad_norm: float = 1.0
    dropout: float = 0.1

    # Multi-task
    use_uncertainty_weighting: bool = True
    use_focal_loss: bool = True
    focal_gamma: float = 2.0

    # Data paths
    fnc_data_dir: str = "data/fnc-1"
    liar_data_dir: str = "data/liar"
    output_dir: str = "output/multitask_bert"

    # Logging & evaluation
    log_steps: int = 50
    eval_epochs: int = 1
    seed: int = 42
