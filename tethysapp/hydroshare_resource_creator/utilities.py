from datetime import datetime
import shutil
import requests
import sqlite3
import uuid
import random
import time
import xmltodict
import os
import collections
from hs_restclient import HydroShare, HydroShareAuthOAuth2, HydroShareNotAuthorized, HydroShareNotFound
from suds.transport import TransportError
from suds.client import Client
from xml.sax._exceptions import SAXParseException
from django.conf import settings
from .app import HydroshareResourceCreator
import json
import logging
import zipfile, io
import traceback

logger = logging.getLogger(__name__)
use_hs_client_helper = True
try:
    from tethys_services.backends.hs_restclient_helper import get_oauth_hs
except Exception as ex:
    use_hs_client_helper = False
    logger.error("tethys_services.backends.hs_restclient_helper import get_oauth_hs: " + ex.message)


def get_user_workspace(request):
    """
    Gets app workspace path.
    
    Arguments:      []
    Returns:        [workspace]
    Referenced By:  [error_report, create_ts_resource, controllers_ajax.chart_data, controllers_ajax.create_layer]
    References:     [app.HydroshareResourceCreator]
    Libraries:      []
    """

    workspace = HydroshareResourceCreator.get_user_workspace(request).path

    return workspace


def get_o_auth_hs(request):
    """
    Gets HydroShare Open Authorization.
    
    Arguments:      [request]
    Returns:        [hs]
    Referenced By:  [controllers_ajax.chart_data, controllers_ajax.create_layer]
    References:     []
    Libraries:      [HydroShareAuthOAuth2, HydroShare]
    """

    if use_hs_client_helper:
        hs = get_oauth_hs(request)
    else:
        hs_instance_name = "www"
        client_id = getattr(settings, "SOCIAL_AUTH_HYDROSHARE_KEY", None)
        client_secret = getattr(settings, "SOCIAL_AUTH_HYDROSHARE_SECRET", None)
        # this line will throw out from django.core.exceptions.ObjectDoesNotExist\
        # if current user is not signed in via HydroShare OAuth
        token = request.user.social_auth.get(provider='hydroshare').extra_data['token_dict']
        hs_hostname = "{0}.hydroshare.org".format(hs_instance_name)
        auth = HydroShareAuthOAuth2(client_id, client_secret, token=token)
        hs = HydroShare(auth=auth, hostname=hs_hostname)

    return hs


def process_file_data(json_file):
    """
    Processes json_file data.
    
    Arguments:      [json_file]
    Returns:        [processed_file_data]
    Referenced By:  [controllers_ajax.chart_data]
    References:     []
    Libraries:      [json]
    """

    with open(json_file) as f:
        data = json.load(f)
        if type(data['timeSeriesReferenceFile']) != dict:
            data = json.loads(data["timeSeriesReferenceFile"])
            data = {"timeSeriesReferenceFile": data}

        for i in range(len(data['timeSeriesReferenceFile']['referencedTimeSeries'])):
            if data['timeSeriesReferenceFile']['referencedTimeSeries'][i]['site']['siteName'] == '':
                data['timeSeriesReferenceFile']['referencedTimeSeries'][i]['site']['siteName'] = 'N/A'
            if data['timeSeriesReferenceFile']['referencedTimeSeries'][i]['site']['siteCode'] == '':
                data['timeSeriesReferenceFile']['referencedTimeSeries'][i]['site']['siteCode'] = 'N/A'
            if data['timeSeriesReferenceFile']['referencedTimeSeries'][i]['variable']['variableName'] == '':
                data['timeSeriesReferenceFile']['referencedTimeSeries'][i]['variable']['variableName'] = 'N/A'
            if data['timeSeriesReferenceFile']['referencedTimeSeries'][i]['variable']['variableCode'] == '':
                data['timeSeriesReferenceFile']['referencedTimeSeries'][i]['variable']['variableCode'] = 'N/A'
            if data['timeSeriesReferenceFile']['referencedTimeSeries'][i]['requestInfo']['networkName'] == '':
                data['timeSeriesReferenceFile']['referencedTimeSeries'][i]['requestInfo']['networkName'] = 'N/A'
            if data['timeSeriesReferenceFile']['referencedTimeSeries'][i]['requestInfo']['refType'] == '':
                data['timeSeriesReferenceFile']['referencedTimeSeries'][i]['requestInfo']['refType'] = 'N/A'
            if data['timeSeriesReferenceFile']['referencedTimeSeries'][i]['requestInfo']['serviceType'] == '':
                data['timeSeriesReferenceFile']['referencedTimeSeries'][i]['requestInfo']['serviceType'] = 'N/A'
            if data['timeSeriesReferenceFile']['referencedTimeSeries'][i]['requestInfo']['url'] == '':
                data['timeSeriesReferenceFile']['referencedTimeSeries'][i]['requestInfo']['url'] = 'N/A'
            if data['timeSeriesReferenceFile']['referencedTimeSeries'][i]['requestInfo']['returnType'] == '':
                data['timeSeriesReferenceFile']['referencedTimeSeries'][i]['requestInfo']['returnType'] = 'N/A'
            if data['timeSeriesReferenceFile']['referencedTimeSeries'][i]['site']['latitude'] == '':
                data['timeSeriesReferenceFile']['referencedTimeSeries'][i]['site']['latitude'] = 'N/A'
            if data['timeSeriesReferenceFile']['referencedTimeSeries'][i]['site']['longitude'] == '':
                data['timeSeriesReferenceFile']['referencedTimeSeries'][i]['site']['longitude'] = 'N/A'
            if data['timeSeriesReferenceFile']['referencedTimeSeries'][i]['method']['methodDescription'] == '':
                data['timeSeriesReferenceFile']['referencedTimeSeries'][i]['method']['methodDescription'] = 'N/A'
            if data['timeSeriesReferenceFile']['referencedTimeSeries'][i]['method']['methodLink'] == '':
                data['timeSeriesReferenceFile']['referencedTimeSeries'][i]['method']['methodLink'] = 'N/A'
        processed_file_data = data['timeSeriesReferenceFile']

        return processed_file_data


def get_data(root_data, keylist, defaultvalue="None"):
    for i in enumerate(keylist):
        data = root_data
        for _, key in enumerate(keylist[i[0]]):
            if isinstance(data, list):
                try:
                    data = data[key]
                except:
                    break
            elif isinstance(data, collections.OrderedDict):
                data = data.get(key, defaultvalue)
            else:
                break
            if data == defaultvalue:
                break
        if data != defaultvalue and not isinstance(data, (collections.OrderedDict, list)):
            return data
    if data == "RAISE_EXCEPTION":
        raise Exception
    else:
        return defaultvalue


def create_ts_resource(res_data):
    """
    Parses Timeseries Layer.

    Arguments:      [file_path, title, abstract]
    Returns:        [counter]
    Referenced By:  [controllers_ajax.create_layer, create_ts_resource]
    References:     [get_user_workspace, load_into_odm2]
    Libraries:      [json, shutil, sqlite3]
    """

    refts_path = res_data['user_dir'] + res_data["res_data_pathname"]

    with open(refts_path, 'r') as refts_file:
        refts_data = ((refts_file.read()).encode(encoding='UTF-8')).replace("'", '"')

    series_count = 0

    json_data = json.loads(refts_data)
    json_data = json_data["timeSeriesReferenceFile"]

    try:
        layer = json_data['referencedTimeSeries']
    except:
        json_data = json.loads(json_data)
        layer = json_data['referencedTimeSeries']

    current_path = os.path.dirname(os.path.realpath(__file__))
    odm_master = os.path.join(current_path, "static_data/ODM2_master.sqlite")
    res_filepath = res_data['user_dir'] + '/' + res_data['res_filename'] + '.odm2.sqlite'
    shutil.copy(odm_master, res_filepath)
    sql_connect = sqlite3.connect(res_filepath, isolation_level=None)
    conn = sql_connect.cursor()
    parse_result = []

    for sub in layer:
        try:
            url = sub['requestInfo']['url']
            site_code = sub['site']['siteCode']
            variable_code = sub['variable']['variableCode']
            start_date = sub['beginDate']
            end_date = sub['endDate']
            return_type = sub['requestInfo']['returnType']
            autho_token = ''
            try:
                wof_uri = sub["wofParams"]["WofUri"]
                data_url = "http://qa-hiswebclient.azurewebsites.net/CUAHSI/HydroClient/WaterOneFlowArchive/" + wof_uri + "/zip"
                cuahsi_zip_file = requests.get(data_url)
                extracted_data = (zipfile.ZipFile(io.BytesIO(cuahsi_zip_file.content))).extractall(res_data["user_dir"])
                with open(res_data["user_dir"] + '/' + extracted_data.namelist()[0], "r") as unzipped_file:
                    values_result = unzipped_file.read()
                    values_result = xmltodict.parse(values_result)
                unzipped_file.close()
                data_root = values_result["soap:Envelope"]["soap:Body"]["TimeSeriesResponse"]["timeSeriesResponse"]
            except:
                if "nasa" in url:
                    headers = {'content-type': 'text/xml'}
                    body = """<?xml version="1.0" encoding="utf-8"?>
                        <soap:Envelope xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" """ + \
                           """xmlns:xsd="http://www.w3.org/2001/XMLSchema" xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/">
                               <soap:Body>
                                   <GetValuesObject xmlns="http://www.cuahsi.org/his/1.0/ws/">
                                       <location>""" + site_code + """</location>
                                    <variable>""" + variable_code + """</variable>
                                    <startDate>""" + start_date + """</startDate>
                                    <endDate>""" + end_date + """</endDate>
                                    <authToken>""" + autho_token + """"</authToken>
                                </GetValuesObject>
                            </soap:Body>
                        </soap:Envelope>"""
                    response = requests.post(url, data=body, headers=headers)
                    values_result = response.content
                    values_result = xmltodict.parse(values_result)
                    data_root = values_result["soap:Envelope"]["soap:Body"]["GetValuesObjectResponse"]["timeSeriesResponse"]
                else:
                    client = connect_wsdl_url(url)
                    values_result = client.service.GetValues(site_code, variable_code, start_date, end_date, autho_token)
                    values_result = xmltodict.parse(values_result)
                    data_root = values_result["timeSeriesResponse"]

            odm_tables = {
                "Datasets":                     """INSERT INTO Datasets (DataSetID, DataSetUUID, DataSetTypeCV, DataSetCode,
                                                DataSetTitle, DataSetAbstract)
                                                VALUES (NULL, ?, ?, ?, ?, ?)""",
                "SamplingFeatures":             """INSERT INTO SamplingFeatures (SamplingFeatureID, SamplingFeatureUUID,
                                                SamplingFeatureTypeCV, SamplingFeatureCode, SamplingFeatureName,
                                                SamplingFeatureDescription, SamplingFeatureGeotypeCV, FeatureGeometry,
                                                FeatureGeometryWKT, Elevation_m, ElevationDatumCV)
                                                VALUES (NULL, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                "SpatialReferences":            """INSERT INTO SpatialReferences(SpatialReferenceID, SRSCode, SRSName,
                                                SRSDescription, SRSLink)
                                                VALUES (NULL, ?, ?, ?, ?)""",
                "Sites":                        """INSERT INTO Sites(SamplingFeatureID, SiteTypeCV, Latitude, Longitude,
                                                SpatialReferenceID)
                                                VALUES (?, ?, ?, ?, ?)""",
                "Methods":                      """INSERT INTO Methods(MethodID, MethodTypeCV, MethodCode, MethodName,
                                                MethodDescription, MethodLink) 
                                                VALUES (NULL, ?, ?, ?, ?, ?)""",
                "Variables":                    """INSERT INTO Variables (VariableID, VariableTypeCV, VariableCode,
                                                VariableNameCV, VariableDefinition, SpeciationCV, NoDataValue)
                                                VALUES (NULL, ?, ?, ?, ?, ?, ?)""",
                "Units":                        """INSERT INTO Units(UnitsID, UnitsTypeCV, UnitsAbbreviation, UnitsName,
                                                UnitsLink)
                                                VALUES (?, ?, ?, ?, ?)""",
                "ProcessingLevels":             """INSERT INTO ProcessingLevels(ProcessingLevelID, ProcessingLevelCode,
                                                Definition, Explanation)
                                                VALUES (NULL, ?, ?, ?)""",
                "People":                       """INSERT INTO People(PersonID, PersonFirstName, PersonLastName)
                                                VALUES (NULL, ?, ?)""",
                "Organizations":                """INSERT INTO Organizations (OrganizationID, OrganizationTypeCV,
                                                OrganizationCode, OrganizationName, OrganizationDescription, 
                                                OrganizationLink) 
                                                VALUES (NULL, ?, ?, ?, ?, ?)""",
                "Affiliations":                 """INSERT INTO Affiliations(AffiliationID, PersonID, OrganizationID,
                                                IsPrimaryOrganizationContact, AffiliationStartDate, PrimaryPhone, 
                                                PrimaryEmail) 
                                                VALUES (NULL, ?, ?, ?, ?, ?, ?)""",
                "Actions":                      """INSERT INTO Actions(ActionID, ActionTypeCV, MethodID, BeginDateTime,
                                                BeginDateTimeUTCOffset, EndDateTime, EndDateTimeUTCOffset, ActionDescription) 
                                                VALUES (NULL, ?, ?, ?, ?, ?, ?, ?)""",
                "ActionBy":                     """INSERT INTO ActionBy(BridgeID, ActionID, AffiliationID, IsActionLead,
                                                RoleDescription) 
                                                VALUES (NULL, ?, ?, ?, ?)""",
                "FeatureActions":               """INSERT INTO FeatureActions(FeatureActionID, SamplingFeatureID, ActionID)
                                                VALUES (NULL, ?, ?)""",
                "Results":                      """INSERT INTO Results(ResultID, ResultUUID, FeatureActionID, ResultTypeCV,
                                                VariableID, UnitsID, ProcessingLevelID, ResultDateTime, ResultDateTimeUTCOffset, 
                                                StatusCV, SampledMediumCV, ValueCount) 
                                                VALUES (NULL, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                "TimeSeriesResults":            """INSERT INTO TimeSeriesResults(ResultID, IntendedTimeSpacing,
                                                IntendedTimeSpacingUnitsID, AggregationStatisticCV) 
                                                VALUES (?, ?, ?, ?)""",
                "TimeSeriesResultValues":       """INSERT INTO TimeSeriesResultValues(ValueID, ResultID, DataValue, ValueDateTime,
                                                ValueDateTimeUTCOffset, CensorCodeCV, QualityCodeCV, TimeAggregationInterval,
                                                TimeAggregationIntervalUnitsID) 
                                                VALUES (NULL, ?, ?, ?, ?, ?, ?, ?, ?)""",
                "DataSetsResults":              """INSERT INTO DataSetsResults(BridgeID, DataSetID, ResultID)
                                                Values (NULL, ?, ?)"""
            }

            if return_type == "WaterML 1.0":
                ds_dataset_code = sub["variable"]["variableCode"]
            elif return_type == "WaterML 1.1":
                ds_dataset_code = sub["variable"]["variableCode"]
            else:
                raise Exception
            conn.execute('SELECT * FROM Datasets WHERE DataSetCode = ?', (ds_dataset_code, ))
            row = conn.fetchone()
            if row is None:

                # ------------------------------------ #
                #   Extracts Data for Datasets Table   #
                # ------------------------------------ #
                if return_type == "WaterML 1.0":
                    ds_dataset_uuid = str(uuid.uuid4())
                    ds_dataset_type_cv = "Multi-time series"
                    ds_dataset_code = ds_dataset_code
                    ds_dataset_title = res_data["res_title"]
                    ds_dataset_abstract = res_data["res_abstract"]
                elif return_type == "WaterML 1.1":
                    ds_dataset_uuid = str(uuid.uuid4())
                    ds_dataset_type_cv = "Multi-time series"
                    ds_dataset_code = ds_dataset_code
                    ds_dataset_title = res_data["res_title"]
                    ds_dataset_abstract = res_data["res_abstract"]                 
                else:
                    raise Exception
                dataset = [ds_dataset_uuid, ds_dataset_type_cv, ds_dataset_code, ds_dataset_title, ds_dataset_abstract]  
                conn.execute(odm_tables["Datasets"], dataset)

            else:
                return None

            if return_type == "WaterML 1.0":
                sf_site_code = get_data(data_root, [["timeSeries", "sourceInfo", "siteCode", "#text"],
                                                    ["timeSeries", "sourceInfo", "siteCode"]], "RAISE_EXCEPTION")
            elif return_type == "WaterML 1.1":
                sf_site_code = get_data(data_root, [["timeSeries", "sourceInfo", "siteCode", "#text"],
                                                    ["timeSeries", "sourceInfo", "siteCode"]], "RAISE_EXCEPTION")
            else:
                raise Exception
            conn.execute('SELECT * FROM SamplingFeatures WHERE SamplingFeatureCode = ?', (sf_site_code, ))
            row = conn.fetchone()
            if row is None:

                # -------------------------------------------- #
                #   Extracts Data for SamplingFeatures Table   #
                # -------------------------------------------- #
                if return_type == "WaterML 1.0":
                    sf_samplingfeature_uuid = str(uuid.uuid4())
                    sf_samplingfeature_type_cv = "Site"
                    sf_samplingfeature_code = sf_site_code
                    sf_samplingfeature_name = get_data(data_root, [["timeSeries", "sourceInfo", "siteName"]], "Unknown")
                    sf_samplingfeature_description = "None"
                    sf_samplingfeature_geotype_cv = "Point"
                    sf_feature_geometry = "Unknown"
                    sf_latitude = get_data(data_root, [["timeSeries", "sourceInfo", "geoLocation", "geogLocation", "latitude"]], "Unknown")
                    sf_longitude = get_data(data_root, [["timeSeries", "sourceInfo", "geoLocation", "geogLocation", "longitude"]], "Unknown")
                    sf_feature_geometry_wkt = "POINT (" + str(sf_longitude) + " " + str(sf_latitude) + ")"
                    sf_elevation_m = get_data(data_root, ["timeSeries", "sourceInfo", "elevation_m", "#text"], "None")
                    sf_elevation_datum_cv = get_data(data_root, [["timeSeries", "sourceInfo", "verticalDatum", "#text"]], "None")
                elif return_type == "WaterML 1.1":
                    sf_samplingfeature_uuid = str(uuid.uuid4())
                    sf_samplingfeature_type_cv = "Site"
                    sf_samplingfeature_code = sf_site_code
                    sf_samplingfeature_name = get_data(data_root, [["timeSeries", "sourceInfo", "siteName"]], "Unknown")
                    sf_samplingfeature_description = "None"
                    sf_samplingfeature_geotype_cv = "Point"
                    sf_feature_geometry = "Unknown"
                    sf_latitude = get_data(data_root, [["timeSeries", "sourceInfo", "geoLocation", "geogLocation", "latitude"]], "Unknown")
                    sf_longitude = get_data(data_root, [["timeSeries", "sourceInfo", "geoLocation", "geogLocation", "longitude"]], "Unknown")
                    sf_feature_geometry_wkt = "POINT (" + str(sf_longitude) + " " + str(sf_latitude) + ")"
                    sf_elevation_m = get_data(data_root, ["timeSeries", "sourceInfo", "elevation_m", "#text"], "None")
                    sf_elevation_datum_cv = get_data(data_root, [["timeSeries", "sourceInfo", "verticalDatum", "#text"]], "None")
                else:
                    raise Exception
                sampling_feature = [sf_samplingfeature_uuid, sf_samplingfeature_type_cv, sf_samplingfeature_code, sf_samplingfeature_name,
                                    sf_samplingfeature_description, sf_samplingfeature_geotype_cv, sf_feature_geometry,
                                    sf_feature_geometry_wkt, sf_elevation_m, sf_elevation_datum_cv]
                conn.execute(odm_tables["SamplingFeatures"], sampling_feature)
                sf_sampling_feature_id = conn.lastrowid

                # --------------------------------------------- #
                #   Extracts Data for SpatialReferences Table   #
                # --------------------------------------------- #
                if return_type == "WaterML 1.0":
                    sr_srs_code = "None"
                    sr_srs_name = "Unknown"
                    sr_srs_description = "The spatial reference is unknown"
                    sr_srs_link = "None"
                elif return_type == "WaterML 1.1":
                    sr_srs_code = "None"
                    sr_srs_name = "Unknown"
                    sr_srs_description = "The spatial reference is unknown"
                    sr_srs_link = "None"
                else:
                    raise Exception
                spatialreference = [sr_srs_code, sr_srs_name, sr_srs_description, sr_srs_link]
                conn.execute(odm_tables["SpatialReferences"], spatialreference)
                sr_spatial_reference_id = conn.lastrowid

                # --------------------------------- #
                #   Extracts Data for Sites Table   #
                # --------------------------------- #
                if return_type == "WaterML 1.0":
                    st_sampling_feature_id = sf_sampling_feature_id
                    st_site_type_cv = get_data(data_root, [["timeSeries", "sourceInfo", "siteProperty", "#text"]], "Unknown")
                    st_latitude = get_data(data_root, [["timeSeries", "sourceInfo", "geoLocation", "geogLocation", "latitude"]], "Unknown")
                    st_longitude = get_data(data_root, [["timeSeries", "sourceInfo", "geoLocation", "geogLocation", "longitude"]], "Unknown")
                    st_spatial_reference_id = sr_spatial_reference_id
                elif return_type == "WaterML 1.1":
                    st_sampling_feature_id = sf_sampling_feature_id
                    st_site_type_cv = get_data(data_root, [["timeSeries", "sourceInfo", "siteProperty", 4, "#text"]], "Unknown")
                    st_latitude = get_data(data_root, [["timeSeries", "sourceInfo", "geoLocation", "geogLocation", "latitude"]], "Unknown")
                    st_longitude = get_data(data_root, [["timeSeries", "sourceInfo", "geoLocation", "geogLocation", "longitude"]], "Unknown")
                    st_spatial_reference_id = sr_spatial_reference_id
                else:
                    raise Exception

                site = [st_sampling_feature_id, st_site_type_cv, st_latitude, st_longitude, st_spatial_reference_id]
                print site
                conn.execute(odm_tables["Sites"], site)

            else:
                st_sampling_feature_id = row[0]

            if return_type == "WaterML 1.0":
                md_method_name = get_data(data_root, [["timeSeries", "method", "MethodDescription"]], "Unknown")
            elif return_type == "WaterML 1.1":
                md_method_name = get_data(data_root, [["timeSeries", "method", "methodDescription"]], "Unknown")
            else:
                raise Exception

            conn.execute('SELECT * FROM Methods WHERE MethodName = ?', (md_method_name, ))
            row = conn.fetchone()
            if row is None:

                # ----------------------------------- #
                #   Extracts Data for Methods Table   #
                # ----------------------------------- #
                if return_type == "WaterML 1.0":
                    md_method_type_cv = "Observation"
                    md_method_code = get_data(data_root, [["timeSeries", "method", "methodCode"]], str(series_count + 1))
                    md_method_name = md_method_name
                    md_method_description = md_method_name
                    md_method_link = get_data(data_root, [["timeSeries", "method", "methodLink"]], "Unknown")
                elif return_type == "WaterML 1.1":
                    md_method_type_cv = "Observation"
                    md_method_code = get_data(data_root, [["timeSeries", "method", "methodCode"]], str(series_count + 1))
                    md_method_name = md_method_name
                    md_method_description = md_method_name
                    md_method_link = get_data(data_root, [["timeSeries", "method", "methodLink"]], "Unknown")
                else:
                    raise Exception

                method = [md_method_type_cv, md_method_code, md_method_name, md_method_description, md_method_link]
                conn.execute(odm_tables["Methods"], method)
                md_method_id = conn.lastrowid

            else:
                md_method_id = row[0]

            if return_type == "WaterML 1.0":
                vr_variable_code = get_data(data_root, [["timeSeries", "variable", "variableCode", "#text"],
                                                        ["timeSeries", "variable", "variableCode"]], "RAISE_EXCEPTION")
            elif return_type == "WaterML 1.1":
                vr_variable_code = get_data(data_root, [["timeSeries", "variable", "variableCode", "#text"],
                                                        ["timeSeries", "variable", "variableCode"]], "RAISE_EXCEPTION")
            else:
                raise Exception

            conn.execute('SELECT * FROM Variables WHERE VariableCode = ?', (vr_variable_code, ))
            row = conn.fetchone()
            if row is None:

                # ------------------------------------- #
                #   Extracts Data for Variables Table   #
                # ------------------------------------- #
                if return_type == "WaterML 1.0":
                    vr_variable_type_cv = get_data(data_root, [["timeSeries", "variable", "generalCategory"]], "Variable")
                    vr_variable_code = vr_variable_code
                    vr_variable_name_cv = get_data(data_root, [["timeSeries", "variable", "variableName"]], "Unknown")
                    vr_variable_definition = "None"
                    vr_speciation_cv = get_data(data_root, [["timeSeries", "variable", "speciation"]], "None")
                    vr_no_data_value = get_data(data_root, [["timeSeries", "variable", "NoDataValue"]], "None")
                elif return_type == "WaterML 1.1":
                    vr_variable_type_cv = get_data(data_root, [["timeSeries", "variable", "generalCategory"]], "Variable")
                    vr_variable_code = vr_variable_code
                    vr_variable_name_cv = get_data(data_root, [["timeSeries", "variable", "variableName"]], "Unknown")
                    vr_variable_definition = "None"
                    vr_speciation_cv = get_data(data_root, [["timeSeries", "variable", "speciation"]], "None")
                    vr_no_data_value = get_data(data_root, [["timeSeries", "variable", "noDataValue"]], "None")
                else:
                    raise Exception
                
                variable = [vr_variable_type_cv, vr_variable_code, vr_variable_name_cv, vr_variable_definition, vr_speciation_cv, vr_no_data_value]
                conn.execute(odm_tables["Variables"], variable)
                vr_variable_id = conn.lastrowid

            else:
                vr_variable_id = row[0]

            if return_type == "WaterML 1.0":
                ut_units_name = get_data(data_root, [["timeSeries", "variable", "timeSupport", "unit", "UnitName"]], "RAISE_EXCEPTION")
            elif return_type == "WaterML 1.1":
                ut_units_name = get_data(data_root, [["timeSeries", "variable", "timeScale", "unit", "unitName"]], "RAISE_EXCEPTION")
            else:
                raise Exception
            
            conn.execute('SELECT * FROM Units WHERE UnitsName = ?', (ut_units_name,))
            row = conn.fetchone()
            if row is None:

                # --------------------------------- #
                #   Extracts Data for Units Table   #
                # --------------------------------- #
                if return_type == "WaterML 1.0":
                    ut_units_id = get_data(data_root, [["timeSeries", "variable", "timeSupport", "unit", "UnitCode"]], "1")
                    ut_units_type_cv = get_data(data_root, [["timeSeries", "variable", "timeSupport", "unit", "UnitType"]], "Unknown")
                    ut_units_abbreviation = get_data(data_root, [["timeSeries", "variable", "timeSupport", "unit", "UnitAbbreviation"]], "Unknown")
                    ut_units_name = ut_units_name
                    ut_units_link = "Unknown"
                elif return_type == "WaterML 1.1":
                    ut_units_id = get_data(data_root, [["timeSeries", "variable", "timeScale", "unit", "unitCode"]], "1")
                    ut_units_type_cv = get_data(data_root, [["timeSeries", "variable", "timeScale", "unit", "unitType"]], "Unknown")
                    ut_units_abbreviation = get_data(data_root, [["timeSeries", "variable", "timeScale", "unit", "unitAbbreviation"]], "Unknown")
                    ut_units_name = ut_units_name
                    ut_units_link = "Unknown"
                else:
                    raise Exception
                
                units = [ut_units_id, ut_units_type_cv, ut_units_abbreviation, ut_units_name, ut_units_link]
                conn.execute(odm_tables["Units"], units)
                ut_units_id = conn.lastrowid

            else:
                ut_units_id = row[0]

            if return_type == "WaterML 1.0":
                pl_processing_level_code = get_data(data_root, [["timeSeries", "values", "qualityControlLevel", "qualityControlLevelCode"],
                                                                ["timeSeries", "values", "qualityControlLevel", "qualityControlLevelCode", "#text"],
                                                                ["timeSeries", "values", "value", 0, "@qualityControlLevel"]], "RAISE_EXCEPTION")
            elif return_type == "WaterML 1.1":
                pl_processing_level_code = get_data(data_root, [["timeSeries", "values", "qualityControlLevel", "qualityControlLevelCode"],
                                                                ["timeSeries", "values", "qualityControlLevel", "qualityControlLevelCode", "#text"],
                                                                ["timeSeries", "values", "value", 0, "@qualityControlLevel"]], "RAISE_EXCEPTION")
            else:
                raise Exception
            
            conn.execute('SELECT * FROM ProcessingLevels WHERE ProcessingLevelCode = ?', (pl_processing_level_code, ))
            row = conn.fetchone()
            if row is None:

                # -------------------------------------------- #
                #   Extracts Data for ProcessingLevels Table   #
                # -------------------------------------------- #
                if return_type == "WaterML 1.0":
                    pl_processing_level_code = pl_processing_level_code
                    pl_definition = get_data(data_root, [["timeSeries", "values", "qualityControlLevel", "definition"]], "None")
                    pl_explanation = get_data(data_root, [["timeSeries", "values", "qualityControlLevel", "explanation"]], "None")
                elif return_type == "WaterML 1.1":
                    pl_processing_level_code = pl_processing_level_code
                    pl_definition = get_data(data_root, [["timeSeries", "values", "qualityControlLevel", "definition"]], "None")
                    pl_explanation = get_data(data_root, [["timeSeries", "values", "qualityControlLevel", "explanation"]], "None")
                else:
                    raise Exception

                processing_levels = [pl_processing_level_code, pl_definition, pl_explanation]
                conn.execute(odm_tables["ProcessingLevels"], processing_levels)
                pl_processing_level_id = conn.lastrowid

            else:
                pl_processing_level_id = row[0]

            if return_type == "WaterML 1.0":
                pp_person_first_name = (get_data(data_root, [["timeSeries", "source", "ContactInformation", "ContactName"]], "Unknown Unknown").split(" "))[0]
                pp_person_last_name = (get_data(data_root, [["timeSeries", "source", "ContactInformation", "ContactName"]], "Unknown Unknown").split(" "))[-1]
            elif return_type == "WaterML 1.1":
                pp_person_first_name = (get_data(data_root, [["timeSeries", "source", "contactInformation", "contactName"]], "Unknown Unknown").split(" "))[0]
                pp_person_last_name = (get_data(data_root, [["timeSeries", "source", "contactInformation", "contactName"]], "Unknown Unknown").split(" "))[-1]

            else:
                raise Exception
            
            conn.execute('SELECT * FROM People WHERE PersonFirstName = ? AND PersonLastName=?', (pp_person_first_name, pp_person_last_name))
            row = conn.fetchone()
            if row is None:

                # ---------------------------------- #
                #   Extracts Data for People Table   #
                # ---------------------------------- #
                if return_type == "WaterML 1.0":
                    pp_person_first_name = pp_person_first_name
                    pp_person_last_name = pp_person_last_name
                    person = [pp_person_first_name, pp_person_last_name]
                elif return_type == "WaterML 1.1":
                    pp_person_first_name = pp_person_first_name
                    pp_person_last_name = pp_person_last_name
                    person = [pp_person_first_name, pp_person_last_name]
                else:
                    raise Exception
                
                conn.execute(odm_tables["People"], person)
                pp_person_id = conn.lastrowid

            else:
                pp_person_id = row[0]

            if return_type == "WaterML 1.0":
                og_organization_name = get_data(data_root, [["timeSeries", "source", "Organization"]], "RAISE_EXCEPTION")
            elif return_type == "WaterML 1.1":
                og_organization_name = get_data(data_root, [["timeSeries", "values", "source", "organization"]], "RAISE_EXCEPTION")
            else:
                raise Exception
            
            conn.execute('SELECT * FROM Organizations WHERE OrganizationName = ?', (og_organization_name, ))
            row = conn.fetchone()
            if row is None:

                # ----------------------------------------- #
                #   Extracts Data for Organizations Table   #
                # ----------------------------------------- #
                if return_type == "WaterML 1.0":
                    og_organization_type_cv = "Unknown"
                    og_organization_code = og_organization_name[:40]
                    og_organization_name = og_organization_name
                    og_organization_description = get_data(data_root, [["timeSeries", "source", "sourceDescription"]], "Unknown")
                    og_organization_link = get_data(data_root, [["timeSeries", "source", "sourceLink"]], "Unknown")
                elif return_type == "WaterML 1.1":
                    og_organization_type_cv = "Unknown"
                    og_organization_code = og_organization_name[:40]
                    og_organization_name = og_organization_name
                    og_organization_description = get_data(data_root, [["timeSeries", "values", "source", "sourceDescription"]], "Unknown")
                    og_organization_link = get_data(data_root, [["timeSeries", "values", "source", "sourceLink"]], "Unknown")
                else:
                    raise Exception
                
                organization = [og_organization_type_cv, og_organization_code, og_organization_name, og_organization_description, og_organization_link]
                conn.execute(odm_tables["Organizations"], organization)
                og_organization_id = conn.lastrowid

            else:
                og_organization_id = row[0]

            conn.execute('SELECT * FROM Affiliations WHERE PersonID = ? AND OrganizationID = ?', (pp_person_id, og_organization_id))
            row = conn.fetchone()
            if row is None:

                # ---------------------------------------- #
                #   Extracts Data for Affiliations Table   #
                # ---------------------------------------- #
                if return_type == "WaterML 1.0":
                    af_person_id = pp_person_id
                    af_organization_id = og_organization_id
                    af_is_primary_organization_contact = 1
                    af_affiliation_start_date = datetime.now()
                    af_primary_phone = get_data(data_root, [["timeSeries", "source", "ContactInformation", "Phone"]], "Unknown")
                    af_primary_email = get_data(data_root, [["timeSeries", "source", "ContactInformation", "Email"]], "Unknown")
                elif return_type == "WaterML 1.1":
                    af_person_id = pp_person_id
                    af_organization_id = og_organization_id
                    af_is_primary_organization_contact = 1
                    af_affiliation_start_date = datetime.now()
                    af_primary_phone = get_data(data_root, [["timeSeries", "values", "source", "contactInformation", "phone"]], "Unknown")
                    af_primary_email = get_data(data_root, [["timeSeries", "values", "source", "contactInformation", "email"]], "Unknown")
                else:
                    raise Exception
                
                affiliation = [af_person_id, af_organization_id, af_is_primary_organization_contact, af_affiliation_start_date, af_primary_phone, af_primary_email]
                conn.execute(odm_tables["Affiliations"], affiliation)
                af_affiliation_id = conn.lastrowid

            else:
                af_affiliation_id = row[0]

            # ----------------------------------- #
            #   Extracts Data for Actions Table   #
            # ----------------------------------- #
            if return_type == "WaterML 1.0":
                ac_action_type_cv = "Observation"
                ac_method_id = md_method_id
                ac_begin_datetime = get_data(data_root, [["timeSeries", "values", "value", 0, "@dateTime"]], "Unknown")
                ac_begin_datetime_offset = get_data(data_root, [["timeSeries", "values", "value", 0, "@timeOffset"]], "Unknown")
                ac_end_datetime = get_data(data_root, [["timeSeries", "values", "value", -1, "@dateTime"]], "Unknown")
                ac_end_datetime_offset = get_data(data_root, [["timeSeries", "values", "value", -1, "@timeOffset"]], "Unknown")
                ac_action_description = "An observation action that generated a time series result."
            elif return_type == "WaterML 1.1":
                ac_action_type_cv = "Observation"
                ac_method_id = md_method_id
                ac_begin_datetime = get_data(data_root, [["timeSeries", "values", "value", 0, "@dateTime"]], "Unknown")
                ac_begin_datetime_offset = get_data(data_root, [["timeSeries", "values", "value", 0, "@timeOffset"]], "Unknown")
                ac_end_datetime = get_data(data_root, [["timeSeries", "values", "value", -1, "@dateTime"]], "Unknown")
                ac_end_datetime_offset = get_data(data_root, [["timeSeries", "values", "value", -1, "@timeOffset"]], "Unknown")
                ac_action_description = "An observation action that generated a time series result."
            else:
                raise Exception
            
            action = [ac_action_type_cv, ac_method_id, ac_begin_datetime, ac_begin_datetime_offset, ac_end_datetime, ac_end_datetime_offset, ac_action_description]
            conn.execute(odm_tables["Actions"], action)
            ac_action_id = conn.lastrowid

            # ------------------------------------ #
            #   Extracts Data for ActionBy Table   #
            # ------------------------------------ #
            if return_type == "WaterML 1.0":
                ab_action_id = ac_action_id
                ab_affiliation_id = af_affiliation_id
                ab_is_action_lead = 1
                ab_role_description = "Responsible party"
            elif return_type == "WaterML 1.1":
                ab_action_id = ac_action_id
                ab_affiliation_id = af_affiliation_id
                ab_is_action_lead = 1
                ab_role_description = "Responsible party"
            else:
                raise Exception
            actionby = [ab_action_id, ab_affiliation_id, ab_is_action_lead, ab_role_description]
            conn.execute(odm_tables["ActionBy"], actionby)

            # ------------------------------------------ #
            #   Extracts Data for FeatureActions Table   #
            # ------------------------------------------ #
            if return_type == "WaterML 1.0":
                fa_sampling_feature_id = sf_sampling_feature_id
                fa_action_id = ac_action_id
            elif return_type == "WaterML 1.1":
                fa_sampling_feature_id = sf_sampling_feature_id
                fa_action_id = ac_action_id
            else:
                raise Exception        
            featureaction = [fa_sampling_feature_id, fa_action_id]
            conn.execute(odm_tables["FeatureActions"], featureaction)
            fa_feature_action_id = conn.lastrowid

            # ------------------------------------- #
            #    Extracts Data for Results Table    #
            # ------------------------------------- #
            if return_type == "WaterML 1.0":
                rt_result_uuid = str(uuid.uuid4())
                rt_feature_action_id = fa_feature_action_id
                rt_result_type_cv = "Time series coverage"
                rt_variable_id = vr_variable_id
                rt_units_id = ut_units_id
                rt_processing_level_id = pl_processing_level_id
                rt_result_datetime = datetime.now()
                rt_result_datetime_utc_offset = -time.timezone / 3600
                rt_status_cv = "Unknown"
                rt_sampled_medium_cv = get_data(data_root, [["timeSeries", "variable", "sampledMedium"]], "Unknown")
                rt_value_count = len(get_data(data_root, [["timeSeries", "values"]]))
            elif return_type == "WaterML 1.1":
                rt_result_uuid = str(uuid.uuid4())
                rt_feature_action_id = fa_feature_action_id
                rt_result_type_cv = "Time series coverage"
                rt_variable_id = vr_variable_id
                rt_units_id = ut_units_id
                rt_processing_level_id = pl_processing_level_id
                rt_result_datetime = datetime.now()
                rt_result_datetime_utc_offset = -time.timezone / 3600
                rt_status_cv = "Unknown"
                rt_sampled_medium_cv = get_data(data_root, [["timeSeries", "variable", "sampledMedium"]], "Unknown")
                rt_value_count = len(get_data(data_root, [["timeSeries", "values"]]))
            else:
                raise Exception        
            result = [rt_result_uuid, rt_feature_action_id, rt_result_type_cv, rt_variable_id, rt_units_id, rt_processing_level_id, rt_result_datetime,
                      rt_result_datetime_utc_offset, rt_status_cv, rt_sampled_medium_cv, rt_value_count]
            conn.execute(odm_tables["Results"], result)
            rt_result_id = conn.lastrowid

            try:
                # ------------------------------------ #
                #    Extracts Data for Time Spacing    #
                # ------------------------------------ #
                if return_type == "WaterML 1.0":
                    tu_units_type_cv = 102
                    tu_units_abbreviation = "Unknown"
                    tu_units_name = "Unknown"
                elif return_type == "WaterML 1.1":
                    tu_units_type_cv = 102
                    tu_units_abbreviation = "Unknown"
                    tu_units_name = "Unknown"
                else:
                    raise Exception        
                time_units = [tu_units_type_cv, tu_units_abbreviation, tu_units_name]
                conn.execute(odm_tables["Units"], time_units)
                tu_units_id = conn.lastrowid
            except:
                tu_units_id = 102

            # ----------------------------------------------- #
            #    Extracts Data for TimeSeriesResults Table    #
            # ----------------------------------------------- #
            if return_type == "WaterML 1.0":
                tr_result_id = rt_result_id
                tr_intended_time_spacing = 30
                tr_time_units_id = tu_units_id
                tr_aggregation_statistic_cv = get_data(data_root, [["timeSeries", "variable", "dataType"]], "Unknown")
            elif return_type == "WaterML 1.1":
                tr_result_id = rt_result_id
                tr_intended_time_spacing = 30
                tr_time_units_id = tu_units_id
                tr_aggregation_statistic_cv = get_data(data_root, [["timeSeries", "variable", "dataType"]], "Unknown")
            else:
                raise Exception        
            timeseries_result = [tr_result_id, tr_intended_time_spacing, tr_time_units_id, tr_aggregation_statistic_cv]
            conn.execute(odm_tables["TimeSeriesResults"], timeseries_result)

            # ---------------------------------------------------- #
            #    Extracts Data for TimeSeriesResultValues Table    #
            # ---------------------------------------------------- #
            if return_type == "WaterML 1.0":
                result_values = []
                num_values = len(data_root["timeSeries"]["values"]["value"])
                for z in range(0, num_values - 1):
                    rv_result_id = rt_result_id
                    rv_data_value = data_root["timeSeries"]["values"]["value"][z]["#text"]
                    rv_value_date_time = data_root["timeSeries"]["values"]["value"][z]["@dateTime"]
                    rv_value_date_time_utc_offset = 0
                    rv_censor_code_cv = get_data(data_root, [["timeSeries", "values", "value", z, "@censorCode"],
                                                             ["timeSeries", "values", "censorCode", "censorCode"]], "Unknown")
                    rv_quality_code_cv = "Unknown"
                    rv_time_aggregation_interval = get_data(data_root, [["timeSeries", "variable", "timeScale"]], "Unknown")
                    rv_time_aggregation_interval_units_id = get_data(data_root, [["timeSeries", "variable", "timeSupport", "unit", "unitCode"]], "Unknown")
                    result_values.append((rv_result_id, rv_data_value, rv_value_date_time, rv_value_date_time_utc_offset, rv_censor_code_cv, 
                                          rv_quality_code_cv, rv_time_aggregation_interval, rv_time_aggregation_interval_units_id))
            elif return_type == "WaterML 1.1":
                result_values = []
                num_values = len(data_root["timeSeries"]["values"]["value"])
                for z in range(0, num_values - 1):
                    rv_result_id = rt_result_id
                    rv_data_value = data_root["timeSeries"]["values"]["value"][z]["#text"]
                    rv_value_date_time = data_root["timeSeries"]["values"]["value"][z]["@dateTime"]
                    rv_value_date_time_utc_offset = 0
                    rv_censor_code_cv = get_data(data_root, [["timeSeries", "values", "value", z, "@censorCode"],
                                                             ["timeSeries", "values", "censorCode", "censorCode"]], "Unknown")
                    rv_quality_code_cv = "Unknown"
                    rv_time_aggregation_interval = get_data(data_root, [["timeSeries", "variable", "timeScale"]], "Unknown")
                    rv_time_aggregation_interval_units_id = get_data(data_root, [["timeSeries", "variable", "timeSupport", "unit", "unitCode"]], "Unknown")
                    result_values.append((rv_result_id, rv_data_value, rv_value_date_time, rv_value_date_time_utc_offset, rv_censor_code_cv, 
                                          rv_quality_code_cv, rv_time_aggregation_interval, rv_time_aggregation_interval_units_id))
            else:
                raise Exception        
            conn.execute("BEGIN TRANSACTION;")
            conn.executemany(odm_tables["TimeSeriesResultValues"], result_values)

            # -------------------------------------------- #
            #    Extracts Data for DataSetResults Table    #
            # -------------------------------------------- #
            if return_type == "WaterML 1.0":
                dr_dataset_id = 1
                dr_result_id = rt_result_id
            elif return_type == "WaterML 1.1":
                dr_dataset_id = 1
                dr_result_id = rt_result_id
            else:
                raise Exception        
            dataset_result = [dr_dataset_id, dr_result_id]
            conn.execute(odm_tables["DataSetsResults"], dataset_result)

            # ------------------------------------------ #
            #    Commits Changes and Closes Connection   #
            # ------------------------------------------ #
            conn.execute("COMMIT;")
            sql_connect.commit()
            sql_connect.close()

            parse_result.append("Complete")

        except Exception, e:
            return_obj = {
                'res_type': None,
                'res_filepath': None,
                'file_extension': None,
                'series_count': None,
                'parse_result': None,
                'error_message': "Server Error: " + str(traceback.format_exc)
            }

            return return_obj

    return_obj = {
        'res_type': 'CompositeResource',
        'res_filepath': res_filepath,
        'file_extension': '.odm2.sqlite',
        'series_count': series_count,
        'parse_result': parse_result,
        'error_message': None
    }

    return return_obj


def update_resource():
    pass


def create_refts_resource(res_data):
    refts_path = res_data['user_dir'] + res_data['res_data_pathname']
    with open(refts_path, 'r') as refts_file:
        refts_data = json.loads((refts_file.read()).encode(encoding='UTF-8'))['timeSeriesReferenceFile']
        try:
            json_test = refts_data["symbol"]
            print json_test
        except:
            refts_data = json.loads(refts_data)
        json_dict = {
            "timeSeriesReferenceFile": {
                "fileVersion": refts_data["fileVersion"],
                "title": refts_data["title"],
                "symbol": refts_data["symbol"],
                "abstract": refts_data["abstract"],
                "keyWords": refts_data["keyWords"],
                "referencedTimeSeries" : []
            }
        }

        for i, refts in enumerate(refts_data['referencedTimeSeries']):
            if i in res_data['selected_resources']:
                sub = {
                    "requestInfo": {
                        "serviceType": refts["requestInfo"]["serviceType"],
                        "refType": refts["requestInfo"]["refType"],
                        "returnType": refts["requestInfo"]["returnType"],
                        "networkName": refts["requestInfo"]["networkName"],
                        "url": refts["requestInfo"]["url"]
                    },
                    "sampleMedium": refts["sampleMedium"],
                    "valueCount": refts["valueCount"],
                    "beginDate": refts["beginDate"],
                    "endDate": refts["endDate"],
                    "site": {
                        "siteCode": refts["site"]["siteCode"],
                        "siteName": refts["site"]["siteName"],
                        "latitude": refts["site"]["latitude"],
                        "longitude": refts["site"]["longitude"]
                    },
                    "variable": {
                        "variableCode": refts["variable"]["variableCode"],
                        "variableName": refts["variable"]["variableName"]
                    },
                    "method": {
                        "methodDescription": refts["method"]["methodDescription"],
                        "methodLink": refts["method"]["methodLink"]
                    }
                }
                json_dict["timeSeriesReferenceFile"]["referencedTimeSeries"].append(sub)

        res_filepath = res_data['user_dir'] + '/' + res_data['res_filename'] + '.refts.json'

        with open(res_filepath, 'w') as res_file:
            json.dump(json_dict, res_file)

        return_obj = {'res_type': 'CompositeResource',
                      'res_filepath': res_filepath,
                      'file_extension': '.refts.json'}

        return return_obj


def connect_wsdl_url(wsdl_url):
    """
    Handles client url errors. 

    Arguments:      [wsdl_url]
    Returns:        [client]
    Referenced By:  [load_into_odm2, ]
    References:     []
    Libraries:      [suds.client.Client]
    """

    try:
        client = Client(wsdl_url)
    except TransportError:
        raise Exception('Url not found')
    except ValueError:
        raise Exception('Invalid url')  # ought to be a 400, but no page implemented for that
    except SAXParseException:
        raise Exception("The correct url format ends in '.asmx?WSDL'.")
    except:
        raise Exception("Unexpected error")

    return client


def trim(string_dic):
    """
    Removes brackets, quotation marks, and commas from a python list.

    Arguments:      [string_dic]
    Returns:        [string_dic]
    Referenced By:  [controllers_ajax.create_layer]
    References:     []
    Libraries:      []
    """

    string_dic = string_dic.strip('[')
    string_dic = string_dic.strip(']')
    string_dic = string_dic.strip('"')
    string_dic = string_dic.replace('"', '')
    string_dic = string_dic.split(',')

    return string_dic
