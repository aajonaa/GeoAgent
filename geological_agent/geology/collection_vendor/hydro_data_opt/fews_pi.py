# Integration scaffold around unchanged upstream source excerpts.
import pandas as pd
from datetime import datetime
import pytz
import re
import io
import gzip
from .fews_untangle import parse_raw
class Utils(object):
    @staticmethod
    def addFilter(self, child):
        setattr(self.Filters, child["id"].replace(".", "_"), {"id": child["id"],
                                                              "name": child.name.cdata,
                                                              "description": child.description.cdata})

    @staticmethod
    def event_client_datetime(event, tz_server, tz_client="Europe/Amsterdam"):
        """
        Get datetime object in client time of an XML Element named event with attributes date and time
        input:
        event     : XML Element named event [eg: obj.TimeSeries.series.event[0]]
        tz_server : datetime abbreviation of the server timezone [eg: "Etc/GMT"]
        tz_client : datetime abbreviation of the client timezone [eg: "Europe/Amsterdam"]

        return
        event_client_time : an datetime object of the event in client timezome

        """
        # convert XML element date string to integer list
        event_server_date = list(
            map(int, event["date"].split("-")))  # -> [yyyy, MM, dd]
        event_server_time = list(
            map(int, event["time"].replace(".",":").split(":")))  # -> [HH, mm, ss, ms]

        # define server time
        if len(event_server_time) == 3:
            server_time = datetime(event_server_date[0], event_server_date[1], event_server_date[2],
                                   event_server_time[0], event_server_time[1], event_server_time[2],
                                   tzinfo=pytz.timezone(tz_server))
        elif len(event_server_time) == 4:
            server_time = datetime(event_server_date[0], event_server_date[1], event_server_date[2],
                                   event_server_time[0], event_server_time[1], event_server_time[2], event_server_time[3]*1000,
                                   tzinfo=pytz.timezone(tz_server))        

        client_timezone = pytz.timezone(tz_client)

        # returns datetime in the new timezone
        event_client_time = server_time.astimezone(client_timezone)

        return event_client_time

    @staticmethod
    def gzip_str(string_):
        """
        write string to gzip compressed bytes object
        """
        out = io.BytesIO()

        with gzip.GzipFile(fileobj=out, mode="w") as fo:
            fo.write(string_.encode())

        bytes_obj = out.getvalue()
        return bytes_obj

    @staticmethod
    def gunzip_bytes_obj(bytes_obj):
        """
        read string from gzip compressed bytes object
        """
        in_ = io.BytesIO()
        in_.write(bytes_obj)
        in_.seek(0)
        with gzip.GzipFile(fileobj=in_, mode="rb") as fo:
            gunzipped_bytes_obj = fo.read()

        return gunzipped_bytes_obj.decode()


def read_timeseries_response(getTimeSeries_response, tz_client, header="longform"):
    """
    function to parse raw xml into python objects
    
    Parameters
    ----------
    getTimeSeries_response : stringIO object
        zeep returned object from a getTimeSeries* query
    header : str
        how to parse the returned header object. Choose from:
        - "multiindex", tries to parse the header into a single pandas.DataFrame where the header is contained as multi-index.
        - "dict", parse the events of the response in a pandas.DataFrame and the header in a seperate dictionary
    format : str
        set the format to parse the raw inpunt stream (choose from 'xml' or 'json', defaults to 'xml)
       
    """
    
    utils = Utils()
    
    if header in ["multiindex", "longform"]:
    
        getTimeSeries_json = parse_raw(getTimeSeries_response)
        timeZoneValue = int(
            float(getTimeSeries_json.TimeSeries.timeZone.cdata))     

        # empty dictionary to fill with dictionary format of each row
        # method adopted to avoid appending to pandas dataframe

        # Etc/GMT* follows POSIX standard, including counter-intuitive sign change: see https://stackoverflow.com/q/51542167/2459096
        if timeZoneValue >= 0:
            timeZone = "Etc/GMT-" + str(timeZoneValue)
        else:
            timeZone = "Etc/GMT+" + str(timeZoneValue)
            
        metacolumns = [
            'moduleInstanceId',
             'qualifierId',
             'parameterId',
             'units',
             'locationId',
             'stationName'
        ]
        
        datacolumns = [
            'datetime',
             'flag',
             'value',
             'user']
            
        data = {key: [] for key in metacolumns + datacolumns}

        # start iteration
        for series in getTimeSeries_json.TimeSeries.series:
            
            # collect metadata
            # GET qualifierId
            try:
                data['qualifierId'].append(series.header.qualifierId.cdata)
            except AttributeError as e:
                data['qualifierId'].append("")
                # print("warning:", e)

            # GET moduleInstanceId
            try:
                data['moduleInstanceId'].append(series.header.moduleInstanceId.cdata)
            except AttributeError as e:
                data['moduleInstanceId'].append("")
                print("warning:", e)

            # GET locationId
            try:
                data['locationId'].append(series.header.locationId.cdata)
            except AttributeError as e:
                print("warning:", e)

#            # GET lat
#            try:
#                lat = float(series.header.lat.cdata)
#            except AttributeError as e:
#                print("warning:", e)
#
#            # GET lon
#            try:
#                lon = float(series.header.lon.cdata)
#            except AttributeError as e:
#                print("warning:", e)

            # GET stationNames
            try:
                data['stationName'].append(series.header.stationName.cdata)
            except AttributeError as e:
                print("warning:", e)

            # GET parameterId
            try:
                data['parameterId'].append(series.header.parameterId.cdata)
            except AttributeError as e:
                print("warning:", e)

            # GET units
            try:
                data['units'].append(series.header.units.cdata)
            except AttributeError as e:
                print("warning:", e)

            
            # collect value flag and user
            if hasattr(series, "event"):
#                print(series.event)
                # GET data values
                times = [(*map(int, re.split('-', event['date'])), *map(int, re.split(':|\.', event['time']))) for event in series.event]
                
                if len(times[0]) == 7:
                    times = [item[:-1] + (item[-1]*1000,) for item in times]

                server_times = [datetime(*times[i], tzinfo=pytz.timezone(timeZone)) for i in range(len(times))] 
                client_timezone = pytz.timezone(tz_client)
                if server_times[0].astimezone(client_timezone) == server_times[0]:
                    dates = server_times
                else:
                    # returns datetime in the new timezone
                    dates = [date.astimezone(client_timezone) for date in server_times]

                data['datetime'].extend(dates)
                data['value'].extend([float(event["value"]) for event in series.event])
                data['flag'].extend([int(event["flag"]) for event in series.event])
                # temp fix for user
                try:
                    data['user'].extend([str(event["user"]) for event in series.event])
                except:
                    pass
                
                nentries = len(series.event)
                    
            else:
                nentries = 1
                for key in ['datetime', 'value', 'flag', 'user']:
                    data[key].append(None)    
                
            # determine number of entries
            if nentries > 1:
                for column in metacolumns:
                    data[column].extend([data[column][-1]] * (nentries - 1))
            

        # CREATE dataframe of timeseries rows dictionary
        df_timeseries = pd.DataFrame(columns=metacolumns+datacolumns)
        for col in metacolumns + datacolumns:
            df_timeseries[col] = data[col]
                    
        if header != "longform":
            df_timeseries.set_index(level=['datetime', "moduleInstanceId", "qualifierId", "parameterId", "units", "locationId", "stationName"], inplace=True)
        else:
            df_timeseries.set_index('datetime', inplace=True)
        
        df_timeseries.sort_values(metacolumns, inplace=True)
        df_timeseries.sort_index(inplace=True)
        
        # Drop user
        if df_timeseries['user'].str.contains('None').any():
            df_timeseries.drop('user', axis=1, inplace=True)
            
    elif header == "dict":
        raise("option 'dict' for parameter 'header' is not yet implemented")
        

        
    return df_timeseries


