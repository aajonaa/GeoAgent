# Integration scaffold around unchanged upstream source excerpts.
import xml.etree.ElementTree as ET
import iso8601
import pytz
import pandas as pd
import re
import os
class BomWater:
    def _parse_float(self, x):
        try:
            if x is None:
                return float('nan')
            return float(x)
        except:
            return float('nan')


    def _parse_time(self, x):
        t = iso8601.parse_date(x).astimezone(pytz.utc)
        return t.replace(tzinfo=None)


    def _parse_quality_code(self, node, qdefault=-1, idefault=""):
        qcodes = [qdefault, idefault]
        if len(node) == 0:
            return qcodes

        if len(node[0]) == 0:
            return qcodes

        for nd in node[0]:
            for key, field in nd.items():
                value = re.sub(".*/", "", field)
                if re.search("interpolation", field):
                    # Found interpolation field
                    qcodes[1] = value
                    break
                elif re.search("qualifier", field):
                    # Found qualifier field
                    qcodes[0] = int(value)
                    break

        return qcodes


    def _parse_default_node(self, default_node):
        default_props = {\
            "quality_code": -1, \
            "unit": "", \
            "interpolation": ""
        }
        if len(default_node)>0:
            if len(default_node[0])>0:
                for nd in default_node[0][0]:
                    for key, field in nd.items():
                        value = re.sub(".*/", "", field)
                        if re.search("interpolation", field):
                            # Found interpolation field
                            default_props["interpolation"] = value
                            break
                        elif re.search("qualifier", field):
                            # Found qualifier field
                            default_props["quality_code"] = int(value)
                            break
                        elif key == 'code':
                            default_props["unit"] = value

        return default_props


    def parse_node_attributes(self, node):
        attribs = {}
        for element in node[0].attrib:
            attribs[element] = node[0].attrib[element]    
        return attribs


    def parse_data(self, response, stations=None):
        root = ET.fromstring(response.text)

        # Unit and default quality code
        prefix = './/{http://www.opengis.net/waterml/2.0}'
        sos_prefix = './/{http://www.opengis.net/sos/2.0}'
        om_prefix = './/{http://www.opengis.net/om/2.0}'
        xlink_prefix = '{http://www.w3.org/1999/xlink}'
        # Parse time series data
        query_observationData = f'{sos_prefix}observationData'
        query_measurement = f'{prefix}MeasurementTVP'
        q_prop = f'{om_prefix}observedProperty'
        q_foi = f'{om_prefix}featureOfInterest'
        q_proc = f'{om_prefix}procedure'
        q_gen_date = f'{prefix}generationDate'
        
        ds = {}
        gen_date = root.findall(q_gen_date)[0].text

        for ob in root.findall(query_observationData):
            data = []
            #Observation Meta data
            default_node = ob.findall(f'{prefix}defaultPointMetadata')
            default_properties = self._parse_default_node(default_node)
            unit = default_properties["unit"]
            qdefault = default_properties["quality_code"]
            idefault = default_properties["interpolation"]

            proc_href = self.parse_node_attributes(ob.findall(q_proc))[f'{xlink_prefix}href']
            prop_href = self.parse_node_attributes(ob.findall(q_prop))[f'{xlink_prefix}href']
            foi_href = self.parse_node_attributes(ob.findall(q_foi))[f'{xlink_prefix}href']
            proc_val = self.parse_node_attributes(ob.findall(q_proc))[f'{xlink_prefix}title']
            prop_val = self.parse_node_attributes(ob.findall(q_prop))[f'{xlink_prefix}title']
            foi_val = self.parse_node_attributes(ob.findall(q_foi))[f'{xlink_prefix}title']
            #Measurement values and associated metadata
            for e in ob.findall(query_measurement):
                info = [None, float('nan'), qdefault, idefault]
                for node in e:
                    if node.tag.endswith("time"):
                        info[0] = self._parse_time(node.text)
                    elif node.tag.endswith("value"):
                        info[1] = self._parse_float(node.text)
                    elif node.tag.endswith("metadata"):
                        qcodes = self._parse_quality_code(node, \
                                            qdefault, idefault)
                        info[2] = qcodes[0]
                        info[3] = qcodes[1]
  
                data.append(info)
            values_name = f'{prop_val} [{unit}]'
            pd_df = pd.DataFrame(data, columns=('time', values_name, 'Quality', 'Interpolation'))
            pd_df = pd_df.set_index('time')
            da = pd_df.to_xarray()
            description = f'Property: {prop_val} [{unit}], Procedure: {proc_val} for Feature: {foi_val}'
            if stations != None:
                coordinates = spatail_utilty.find_station_coordinates_from(os.path.basename(foi_href), stations, None)
            else:
                coordinates = ''
            da = da.assign_attrs(
                units=unit, 
                description=description,
                procedure = os.path.basename(proc_href),
                property = prop_val,
                generated_date = f'{gen_date}',
                station_no = f'{foi_href}',
                coordinates = coordinates,
                long_name=f'{foi_val}:{prop_val}', 
                missing_data_value = 'nan')

            ds[f'{foi_href}'] = da
 
        return ds


