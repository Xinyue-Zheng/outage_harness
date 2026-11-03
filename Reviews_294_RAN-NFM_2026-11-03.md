# Reviews #294 (RAN-NFM submission)

## Review #294A

**Overall merit:** 3. Weak accept
**Reviewer expertise:** 4. Expert

### Paper summary

The paper proposes a novel framework for Radio Access Network (RAN) profiling and behavior prediction. It addresses the scalability and transferability issues by introducing a self-supervised foundation model. The paper derives two task-adapted variants one that integrates the pre-trained model with LLM-derived semantic representations and a lightweight variant optimized for real-time inference. The system is evaluated on six months of nationwide production network data on three core RAN tasks with substantial accuracy improvements over production baselines and alternative encoder designs.

### Strengths

The system is evaluated on a real production network and shows performance enhancement.

### Weaknesses

Limited novelty. Yet another paper about foundation models.
Not enough information to replicate the work.
System is evaluated on only a single provider. Not clear if it can generalize to other networks.

### Comments for authors

Although the work has an impact on an actual production network, which is significant, there are a number of issues that need to be addressed:

It would be better to provide detailed XAI analysis and results to show more insights about how the model works and the advantage of LLMs and the core model in which scenario.

One limitation of the paper is how extensible the proposed model is to other providers, technologies (4G to 6G), and vendors. This needs to be qualtified.

Although the system is evaluated over a 6 months period, it would be good to add evaluations under network stress events (e.g., sudden severe weather outages or high-density stadium gatherings). This may have occurred during the t months period but they are averaged out.

The paper should provide data for replicability.

## Review #294B

**Overall merit:** 3. Weak accept
**Reviewer expertise:** 2. Some familiarity

### Paper summary

RAN management requires accurately predicting the system performance (throughput, power) under diverse network configuration settings. Traditional RAN management systems use rule-based heuristics which requires manual tuning. Some recent systems also use machine learning-based approach that are often task specific and thus requires frequent re-training.

To address this issue, RAN-NFM borrows the idea of foundation models in LLMs, where a single model is pre-trained to learn general, re-usable representations. Then, the model is fine-tuned for separately for each downstream task.

Authors evaluated RAN-NFM on a variety of tasks, including RANPerf (classifies whether a configuration change results in >30% throughput gain), EngSav (predicts throughput), and EngCon (predicts energy consumption). Compared with several baselines, RAN-NFM show improved accuracy for each task. Additionally, RANPerf has been actually deployed with a U.S. service provider, which was shown to provide configuration decisions that lead to higher throughput than the baselines.

### Strengths

RAN configuration is an important and timely operation problem. It is also a relevant topic for the MobiCom community.

The idea of using a pretrained model plus fine-tuning for individual downstream tasks is an intuitive design. The intuition has been shown feasible by related prior works (e.g., NetLLM), and has real benefits in reducing re-training costs.

RAN-NFM is being evaluated with real world workloads, and has been deployed in the real world with a U.S. operator, showing its applicability to real world scenarios.

### Weaknesses

I feel the paper would benefit from a discussion of the generalizability of the pre-trained model. For example, (1) RAN-NFM is currently trained on 21 cell-level configuration features -- if certain features got removed or added in the future, does that require re-training the base model? (2) If the timeseries format changes in the future (column gets removed or added), would that require re-training the base model?

There seems a few prior works for pre-training foundational models for network applications. Though not directly related to RAN, they seem to share the similar idea of foundation model pre-training. If they are related, it would be good to include them in the related works for completeness:

- NetGPT: Generative Pretrained Transformer for Network Traffic: https://arxiv.org/abs/2304.09513
- Netmamba: Efficient Network Traffic Classification Via Pre-Training Unidirectional Mamba: https://ieeexplore.ieee.org/document/10858569

Out of curiosity: is there a reason for choosing linear attention (equation 1) over traditional softmax attention? Softmax v.s. linear attention has accuracy-cost trade-offs -- wonder if linear attention's reduced cost make up for its accuracy loss?

Figure 1 is missing the values on y-axis, and figure 5 (b) (c) is missing values on x-axis. Adding those values will make the readers understand the figures better.

Not sure if the authors used the submission templates. The fonts looks different?

## Review #294C

**Overall merit:** 1. Reject
**Reviewer expertise:** 3. Knowledgeable

### Paper summary

The paper presents RAN-NFM, a framework building upon a pre-trained multi-modal foundation model that has learned general, reusable representations of a RAN. Such a generic RAN-NFM can then be fine tuned to solve specific RAN-related tasks.

### Strengths

The premise of the paper is timely and valuable, the time as come for our community to explore foundation models.

Tests in a production RAN for 6 months.

### Weaknesses

The task design choices are arbitrary and not convincing.

- In RANPerf, sector-level downlink throughput increase is just one of the many metrics one could look into, and circumstantiating the analysis to that specific metric may hide issues in the solution: e.g., configurations increasing downlink throughput may incur into decreased uplink performance, reduced fairness across users, or added latency, which are ignored. On the same page, the decision to formulate the RANPerf as a classification problem does not appear to be rooted in any other reason than simplifying the task---possibly to meet the performance limits of RAN-NFM.
- EngSav is, to the best of my knowledge, an artificial problem: cell shutdown does not work in the way presented in Sec.2.4, rather it is based on real-time monitoring of power group KPIs (see, e.g., Ma et al., "TWINERGY: Digital Twin Empowered Practical Energy Saving in Heterogeneous Mobile Networks", ACM MobiHoc 2026). On a related point, I miss evidence that StaF-MLP has been a "highly competitive production solution for years".
- The motivation behind EngCon is not clear at all: energy consumption can be immediately estimated from RAN equipment and load information (see, e.g., Ma et al., "Sustainable connections: Exploring energy efficiency in 5g networks", ACM CoNEXT 2024), hence predicting future loads makes this task unnecessary. In addition, information on how ground truth about the energy consumption of the RAN is derived is omitted in the text, and no relevant KPI is in Tab.7.

The choice of baselines is questionable as it does not include traditional rule-based and heuristic approaches that are widely adopted in production. Without those references, it is not possible to determine if RAN-NFM actually offers gains over what it deployed today.

Even when disregarding the point above, the outcome of the comparative performance evaluation does not seem to justify the superiority of RAN-NFM. When results are quantified properly, e.g., in Tab.2, the overall performance is just bad (0.3 F1-score indicates that the solution is not viable in production). When results are only presented in relative terms, e.g., in Tab.3-4, gains over baselines are not large and it is impossible to understand if they are significant---both statistically (e.g., no standard deviation) and in practice (e.g., is the '1' reference a bad performance hence staying within 10% of it is equally bad?). In some cases, neither relative or absolute figures are provided, e.g., in Fig.5-6 where the x axis has no numbers---making it impossible to understand if we are looking at high or low error values. Overall, the way results are presented leaves me with the unfortunate feelings that numbers were tinkered in a way that makes results look good.

The same applies to the months-long field tests, which are per-se an achievement.

- First, information about the scale and configuration of the real-world deployment is insufficient: how many cells/base stations are involved in the trial, in which type of region(s) are they deployed, which kind of traffic dynamics are present in the region(s)? A minimum presentation of the scenario is needed to be able to interpret the results.
- Second, the amount of results reported is underwhelming for six months of evaluation in a production network: we have Fig.6 and a (small) Tab.6, which provide very limited insights in the outcome of the experiments. With such an unprecedented evaluation, I would have expected that the whole performance evaluation to be heavily focused on real-world results.
- In all cases, the performance gain over the baselines is not as significant as the authors claim in the text: on the one hand, improvements in the RANPerf are limited to niche cases, i.e., cells for which RAN-NFM is very confident (k<5) and throughput is especially low (Btm-20 and Mid-60); on the other hand, gains are basically nil over NetLLM and often anecdotical over Auric-XGB. Importantly, in some cases (Top-20), the results can be negative, meaning that the proposed configuration harms the system: as there is no information about how many cells are in each data sample (e.g., how many cells are in the Top-k with k<5 of Btm-20) nor what the original throughput was, it may be that the overall throughput balance among all cells is negative (e.g., if the disruption caused to Top-20 cells that handle a high demand is in fact higher---in terms of sheer served Mbps---of the advantage brought to low-demand cells).

I would have also appreciated a more thorough discussion of the compute cost of RAN-NFM with respect to the baselines. The figures about GPU usage reported in the paper are pretty scary to be honest.

### Comments for authors

Data splits, data masking, data resampling, data labeling, and the way testing happen are often presented in a confused way, with verbose and redundant text that makes it very hard to judge if the evaluation is carried out in a correct way. I strongly recommend revising the writing to make the presentation of the train/test procedures plain.

While the task-agnostic RAN-NFM-Base backbone is trained in a self-supervised way, task specialization is fully supervised and requires ground truth: this aspect is not sufficiently clear through the abstract, introduction, and technical discussion. In addition, in several proposed tasks, it is not clear how such ground truth is obtained: where do targets 'y' come from in settings where the decision enacted by RAN-NFM affects the evolution of the system?

Results supporting the ablation study outcome that "incorporating historical throughput degrades performance" in the EngSav task should be provided in the appendix. In fact, the claim that "historical throughput reflects full network capacity under normal conditions" applies to all KPIs in Table 7, hence it is not clear why only that specific KPI should be excluded.

Fonts in Fig.2 and Fig.3 are too small.

Adding a scale on the y axis of Fig.1 would make the plot more honest.

### What, if anything, could convince you to accept this paper?

The whole performance evaluation should be overhauled.

## Review #294D

**Overall merit:** 2. Weak reject
**Reviewer expertise:** 3. Knowledgeable

### Paper summary

The paper proposes an ML model that uses multi-modal RAN data to build a base model called RAN-NFM-Base, which is trained in self-supervised mode. This model can then be fine-tuned for the task using the RAN-NFM-Core and RAN-NFM-Pro model heads. The model is used with three use cases named RANPerf (Configuration Parameter Tuning for RAN Performance Optimization), EngSav (Throughput Prediction for Energy Saving), EngCon (Energy Consumption Prediction). The model shows performance improvements for these use cases.

### Strengths

The real-world deployment and experiments
High-level motivation to create a RAN-specific model is good.

### Weaknesses

- Lack of quantitative motivation
- Although the model is performing better than the baselines, overall the model is performing poorly.
- Which further raises questions: are the selected use cases the right choice?
- Generalizability is unclear, as RAN has diverse use cases, some of which require sub-ms time series data as well. The model is trained on hourly time-series data.
- Marginal performance improvement compared to baselines.
- The paper does not show whether inference is practical at network scale, and the full version looks expensive to run.
- The main claim, that one pretrained model can be reused across tasks, is not directly tested.
- The deployment has no controlled test or testbed, so its benefits are not clearly shown.

### Comments for authors

Thank you for your submission to MobiCom 27. Here are some comments that can be helpful.

In Tables 2 and Table 3, the model performs better than the baselines, but overall model performance is poor.

A discussion on how the real-world deployment experiments ensure a fair comparison. This is important to understand, as some gains can also come from statistical imbalance.

Inference time vs. accuracy tradeoff plots are not explicitly shown.

The motivation argues that rule-based systems are inadequate, but the evaluation includes no rule-based or simple heuristic baseline. Adding one, such as a threshold on sector throughput or load, would show how much of the gain actually requires a learned model.

Please state how often each task must run, and whether inference keeps up with that across the whole network.

Please report the hardware and total cost of running inference across the whole network, including the production baselines.

Please compare the model with and without pretraining, to show how much of the gain comes from pretraining itself.

Please report what changed in the live network, such as throughput gained or energy saved.

Please compare against a control group of sectors under the same conditions.

## Review #294E

**Overall merit:** 3. Weak accept
**Reviewer expertise:** 3. Knowledgeable

### Paper summary

The paper presents a foundation model for RAN that combines tabular and time-series encoders with self-supervised pretraining and task-specific fine-tuning. The model supports multiple operational tasks. Evaluation on data from a commercial cellular network demonstrates improvements over several ML baselines, and also shows production deployment results.

### Strengths

Well-engineered ML system supporting multiple RAN prediction tasks with a shared pretrained model.
Competitive results against reasonable baselines, including evaluation in a production environment.

### Weaknesses

Unclear RAN-specific contribution and insufficient evidence of the benefits of pretraining and generalization.
Weak problem formulation and insufficiently clear evaluation methodology and operational significance.

### Comments for authors

The paper presents a technically sound ML system, with encouraging results across several RAN management tasks and valuable evidence from a production environment. However, I have several concerns regarding the problem formulation and the claimed generality of the approach, and the significance of the experimental results.

One of the important concerns is the motivation and RAN-specific contribution. The proposed approach appears to be a general framework for learning representations from operational telemetry and applying them to downstream prediction tasks. It is unclear which aspects of the problem are specific to cellular networks and which properties of RANs motivate the architectural choices. Similar approaches could potentially be applied to anomaly detection or performance forecasting in other complex systems with observable metrics. This is not necessarily a limitation, but the paper should clearly establish what makes the RAN setting technically challenging and how the proposed system addresses these challenges. At present, the emphasis is predominantly on ML methodology rather than on the underlying networking problems and their significance.

The scope of generalization is unclear. The approach appears to rely on pretraining over historical operational data that already captures the configurations and operating conditions relevant to the downstream tasks. It is unclear how the model performs when encountering configurations, operating conditions, or system behaviors not represented in the training data. In particular, how sensitive are the pretrained representations to the underlying software implementation? Would a RAN software update that changes the relationship between configuration parameters and performance require retraining the model? The paper should explain which forms of generalization are supported and which require additional training.

The paper also does not convincingly demonstrate the value of pretraining. Although the shared pretrained model supports several downstream tasks, it is unclear what knowledge is acquired during pretraining that could not be learned through conventional supervised training. You should compare the proposed approach against the same architecture trained from scratch and establish whether pretraining improves performance, reduces labeled-data requirements, or enables generalization to previously unseen conditions. Without such evidence, the foundation-model contribution remains insufficiently established.

The definition of the downstream tasks and their training assumptions need substantial clarification. Section 4.2 introduces several use cases without clearly distinguishing the information available during pretraining, fine-tuning, and inference. For example, RANPerf is formulated as a classification problem that predicts whether a configuration change improves a target KPI. Does the model need to observe the performance of different configurations during pretraining or fine-tuning to make this prediction? Can it predict the effects of previously unseen configuration changes, or does it primarily interpolate between configurations represented in the training data? Similar questions arise for the other use cases. For each application, the paper should explicitly define the inputs, prediction targets, training information, and evaluation conditions, including what information is unavailable to the model at inference time. This is necessary to establish what the system actually learns and which operational problems it can solve.

The problem formulation should be substantially improved. The abstract and introduction do not clearly establish which RAN performance metrics or operational problems motivate the work. It is difficult to determine whether the intended applications concern channel prediction, handover optimization, system failures, configuration management, or other aspects of RAN operation. Section 2.2 introduces the proposed solution methodology before adequately defining the problem. The paper should first explain the operational objectives, the available observations, and the limitations of existing solutions. Only then it should introduce the foundation-model approach. This would also help distinguish the proposed work from a generic anomaly detection or forecasting framework evaluated on cellular-network data.

The description and motivation of the model inputs are insufficiently clear. Section 3.1 introduces self-supervised learning from unlabeled data without first clearly explaining the nature of these data, their relationship to RAN operation, and why they are appropriate for the proposed learning objectives. Similarly, the choice of a tabular encoder is presented without sufficiently motivating which input characteristics require this architecture. Table 1 surveys existing approaches but does not convincingly motivate the use of LLMs or establish what capabilities they provide beyond conventional representation-learning techniques. You should make the relationship between the characteristics of RAN telemetry, the selected model components, and the intended operational tasks more explicit.

The event-injection mechanism in Section 3.5 is also unclear. The relationship between the action vector a_t_{n+1} and the observations x needs clarification. Since configuration parameters are already included in the model inputs, should the action not be represented as part of these observations? If the action is represented separately, you should define it at the beginning of Section 3.5 and explain why this separation is necessary. It is also unclear whether actions are incorporated during pretraining or introduced only during task-specific fine-tuning. A more precise description of the inputs and training procedure would help establish the role of this mechanism.

### What, if anything, could convince you to accept this paper?

If the authors address my two main weaknesses, both of which could potentially be addressed in writing
