import pandas as pd
import numpy as np
import re
import bayespy

import logging
import os
from sklearn.cross_validation import KFold
from sklearn.metrics import accuracy_score

pattern = re.compile("([A-Z]{1})([0-9]{1,3})")

def get_cabin_floor_and_number(cabin):
    if not isinstance(cabin, str):
        return "", np.nan

    cabins = cabin.split(" ")
    for cabin in cabins:
        match = re.match(pattern, cabin)
        if match is not None:
            floor = match.group(1)
            number = match.group(2)

            return floor, number
    return "", np.nan

def main():
    db_folder = bayespy.utils.get_path_to_parent_dir(__file__)
    titanic = pd.read_csv(os.path.join(db_folder, "data/train.csv"))

    titanic['Floor'], titanic['CabinNumber'] = zip(*titanic.Cabin.map(get_cabin_floor_and_number))
    titanic.CabinNumber = titanic.CabinNumber.astype(float)
    titanic.Floor.replace("", np.nan, inplace=True)
    titanic.drop(['Cabin', 'Ticket', 'Name', 'PassengerId'], inplace=True, axis=1)

    logger = logging.getLogger()
    logger.addHandler(logging.StreamHandler())
    logger.setLevel(logging.INFO)

    # attach/ startup the JVM
    bayespy.jni.attach(logger)

    # get a good guess as to whether the variable is discrete/ continuous
    auto = bayespy.data.AutoType(titanic)
    network_factory = bayespy.network.NetworkFactory(logger)

    discrete = titanic[list(auto.get_discrete_variables())]
    continuous = titanic[list(auto.get_continuous_variables())]

    # write data to the temporary sqllite db
    with bayespy.data.DataSet(titanic, db_folder, logger) as dataset:

        # learn the model structure using built-in algorithm
        tpl = bayespy.template.NetworkWithoutEdges(discrete=discrete,
                                                   continuous=continuous)

        structure_tpl = bayespy.template.AutoStructure(tpl, dataset, logger)

        # this gives us a Java network object
        learned_network = structure_tpl.create(network_factory)

        # Or, use a standard template, which generally gives good performance
        mixture_naive_bayes_tpl = bayespy.template.MixtureNaiveBayes(logger, discrete=discrete, continuous=continuous)

        k_folds = 3

        kf = KFold(titanic.shape[0], n_folds=k_folds, shuffle=True)
        score = 0
        # use cross validation to try and predict whether the individual survived or not
        for k, (train_indexes, test_indexes) in enumerate(kf):
            model = bayespy.model.NetworkModel(
                            mixture_naive_bayes_tpl.create(network_factory),
                            dataset.subset(train_indexes), logger)

            # result contains a bunch of metrics regarding the training step
            training_result = model.train()

            # need to create a new model from the trained network, and use this to test the accuracy of the trained model.
            test_model = bayespy.model.NetworkModel(training_result['network'], dataset.subset(test_indexes), logger)

            # note that we've not 'dropped' the target data anywhere, this will be retracted when it's queried,
            # by specifying query_options.setQueryEvidenceMode(bayesServerInference().QueryEvidenceMode.RETRACT_QUERY_EVIDENCE)
            results = test_model.batch_query(bayespy.model.QueryMostLikelyState("Survived", output_dtype=titanic['Survived'].dtype))

            # Each query just appends a column/ columns on to the original dataframe, so results is the same as titanic.iloc[test_indexes],
            # with (in this case) one additional column called 'Survived_maxlikelihood', joined to the original.
            score += accuracy_score(y_pred=results['Survived_maxlikelihood'].tolist(), y_true=results['Survived'].tolist())

        logger.info("Average score was {}. Baseline accuracy is about 0.61.".format(score / k_folds))

if __name__ == "__main__":
    main()
